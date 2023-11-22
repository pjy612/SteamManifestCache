import os
import git
import sys
import json
import time
import base64
import gevent
import logging
import argparse
import platform
import requests
import functools
import traceback
import subprocess
from pathlib import Path
from steam.enums import EResult
from push import push, push_data
from multiprocessing.pool import ThreadPool
from multiprocessing.dummy import Pool, Lock
from steam.guard import generate_twofactor_code
from DepotManifestGen.main import MySteamClient, MyCDNClient, get_manifest, BillingType, Result

lock = Lock()
sys.setrecursionlimit(100000)
parser = argparse.ArgumentParser()
parser.add_argument('-c', '--credential-location', default=None)
parser.add_argument('-l', '--level', default='INFO')
parser.add_argument('-p', '--pool-num', type=int, default=8)
parser.add_argument('-r', '--retry-num', type=int, default=3)
parser.add_argument('-t', '--update-wait-time', type=int, default=86400)
parser.add_argument('-k', '--key', default=None)
parser.add_argument('-i', '--init-only', action='store_true', default=False)
parser.add_argument('-C', '--cli', action='store_true', default=False)
parser.add_argument('-P', '--no-push', action='store_true', default=False)
parser.add_argument('-u', '--update', action='store_true', default=False)
parser.add_argument('-a', '--app-id', dest='app_id_list', action='extend', nargs='*')
parser.add_argument('-U', '--users', dest='user_list', action='extend', nargs='*')

class MyJson(dict):

    def __init__(self, path):
        super().__init__()
        self.path = Path(path)
        self.load()

    def load(self):
        if not self.path.exists():
            self.dump()
            return
        with self.path.open() as f:
            self.update(json.load(f))

    def dump(self):
        with self.path.open('w') as f:
            json.dump(self, f)


class LogExceptions:
    def __init__(self, fun):
        self.__callable = fun
        return

    def __call__(self, *args, **kwargs):
        try:
            return self.__callable(*args, **kwargs)
        except KeyboardInterrupt:
            raise
        except:
            logging.error(traceback.format_exc())


class ManifestAutoUpdate:
    log = logging.getLogger('ManifestAutoUpdate')
    ROOT = Path('data').absolute()
    users_path = ROOT / Path('users.json')
    app_info_path = ROOT / Path('appinfo.json')
    user_info_path = ROOT / Path('userinfo.json')
    two_factor_path = ROOT / Path('2fa.json')
    key_path = ROOT / 'KEY'
    git_crypt_path = ROOT / ('git-crypt' + ('.exe' if platform.system().lower() == 'windows' else ''))
    repo = git.Repo()
    app_lock = {}
    pool_num = 8
    retry_num = 3
    remote_head = {}
    update_wait_time = 86400
    tags = set()

    def __init__(self, credential_location=None, level=None, pool_num=None, retry_num=None, update_wait_time=None,
                 key=None, init_only=False, cli=False, app_id_list=None, user_list=None, Skip=False):
        if level:
            level = logging.getLevelName(level.upper())
        else:
            level = logging.INFO
        logging.basicConfig(format='%(asctime)s - %(pathname)s[line:%(lineno)d] - %(levelname)s: %(message)s',
                            level=level)
        logging.getLogger('MySteamClient').setLevel(logging.WARNING)
        self.init_only = init_only
        self.cli = cli
        self.pool_num = pool_num or self.pool_num
        self.retry_num = retry_num or self.retry_num
        self.update_wait_time = update_wait_time or self.update_wait_time
        self.credential_location = Path(credential_location or self.ROOT / 'client')
        self.log.debug(f'credential_location: {credential_location}')
        self.key = key
        self.app_sha = None
        if not self.check_app_repo_local('app'):
            if self.check_app_repo_remote('app'):
                self.log.info('Pulling remote app branch!')
                self.repo.git.fetch('origin', 'app:app')
            else:
                try:
                    self.log.info('Getting the full branch!')
                    #self.repo.git.fetch('--unshallow')
                except git.exc.GitCommandError as e:
                    self.log.debug(f'Getting the full branch failed: {e}')
                self.app_sha = self.repo.git.rev_list('--max-parents=0', 'HEAD').strip()
                self.log.debug(f'app_sha: {self.app_sha}')
                self.repo.git.branch('app', self.app_sha)
        if not self.app_sha:
            self.app_sha = self.repo.git.rev_list('--max-parents=0', 'app').strip()
            self.log.debug(f'app_sha: {self.app_sha}')
        if not self.check_app_repo_local('data'):
            if self.check_app_repo_remote('data'):
                self.log.info('Pulling remote data branch!')
                self.repo.git.fetch('origin', 'data:origin_data')
                self.repo.git.worktree('add', '-b', 'data', 'data', 'origin_data')
            else:
                self.repo.git.worktree('add', '-b', 'data', 'data', 'app')
        data_repo = git.Repo('data')
        if data_repo.head.commit.hexsha == self.app_sha:
            self.log.info('Initialize the data branch!')
            self.download_git_crypt()
            self.log.info('Key being generated!')
            subprocess.run([self.git_crypt_path, 'init'], cwd='data')
            subprocess.run([self.git_crypt_path, 'export-key', self.key_path], cwd='data')
            self.log.info(f'Your key path: {self.key_path}')
            with self.key_path.open('rb') as f:
                self.key = f.read().hex()
            self.log.info(f'Your key hex: {self.key}')
            self.log.info(
                f'Please save this key to Repository secrets\nIt\'s located in Project -> Settings -> Secrets -> Actions -> Repository secrets')
            with (self.ROOT / '.gitattributes').open('w') as f:
                f.write('\n'.join(
                    [i + ' filter=git-crypt diff=git-crypt' for i in ['users.json', 'client/*.key', '2fa.json']]))
            data_repo.git.add('.gitattributes')
        if self.key and self.users_path.exists() and self.users_path.stat().st_size > 0:
            with Path(self.ROOT / 'users.json').open('rb') as f:
                content = f.read(10)
            if content == b'\x00GITCRYPT\x00':
                self.download_git_crypt()
                with self.key_path.open('wb') as f:
                    f.write(bytes.fromhex(self.key))
                subprocess.run([self.git_crypt_path, 'unlock', self.key_path], cwd='data')
                self.log.info('git crypt unlock successfully!')
        if not self.credential_location.exists():
            self.credential_location.mkdir(exist_ok=True)
        self.account_info = MyJson(self.users_path)
        self.user_info = MyJson(self.user_info_path)
        self.app_info = MyJson(self.app_info_path)
        self.two_factor = MyJson(self.two_factor_path)
        self.log.info('Waiting to get remote tags!')
        self.get_remote_tags()
        self.update_user_list = [*user_list] if user_list else []
        self.update_app_id_list = []
        if app_id_list:
            self.update_app_id_list = list(set(int(i) for i in app_id_list if i.isdecimal()))
            for user, info in self.user_info.items():
                if info['enable'] and info['app']:
                    for app_id in info['app']:
                        if app_id in self.update_app_id_list:
                            self.update_user_list.append(user)
        self.update_user_list = list(set(self.update_user_list))

    def download_git_crypt(self):
        if self.git_crypt_path.exists():
            return
        self.log.info('Waiting to download git-crypt!')
        url = 'https://github.com/AGWA/git-crypt/releases/download/0.7.0/'
        url_win = 'git-crypt-0.7.0-x86_64.exe'
        url_linux = 'git-crypt-0.7.0-linux-x86_64'
        url = url + (url_win if platform.system().lower() == 'windows' else url_linux)
        try:
            r = requests.get(url)
            with self.git_crypt_path.open('wb') as f:
                f.write(r.content)
            if platform.system().lower() != 'windows':
                subprocess.run(['chmod', '+x', self.git_crypt_path])
        except requests.exceptions.ConnectionError:
            traceback.print_exc()
            exit()

    def get_manifest_callback(self, username, app_id, depot_id, manifest_gid, args):
        result = args.value
        if not result:
            self.log.warning(f'User {username}: get_manifest return {result.code.__repr__()}')
            return
        app_path = self.ROOT / f'depots/{app_id}'
        try:
            delete_list = result.get('delete_list') or []
            manifest_commit = result.get('manifest_commit')
            if len(delete_list) > 1:
                self.log.warning('Deleted multiple files?')
            self.set_depot_info(depot_id, manifest_gid)
            app_repo = git.Repo(app_path)
            with lock:
                if manifest_commit:
                    app_repo.create_tag(f'{depot_id}_{manifest_gid}', manifest_commit)
                else:
                    if delete_list:
                        app_repo.git.rm(delete_list)
                    app_repo.git.add(f'{depot_id}_{manifest_gid}.manifest')
                    app_repo.git.add('Key.vdf')
                    app_repo.git.add('config.json')
                    app_repo.git.add('appinfo.vdf')
                    app_repo.index.commit(f'Update depot: {depot_id}_{manifest_gid}')
                    app_repo.create_tag(f'{depot_id}_{manifest_gid}')
        except KeyboardInterrupt:
            raise
        except:
            logging.error(traceback.format_exc())
        finally:
            with lock:
                if int(app_id) in self.app_lock:
                    self.app_lock[int(app_id)].remove(depot_id)
                    if int(app_id) not in self.user_info[username]['app']:
                        self.user_info[username]['app'].append(int(app_id))
                    if not self.app_lock[int(app_id)]:
                        self.log.debug(f'Unlock app: {app_id}')
                        self.app_lock.pop(int(app_id))

    def set_depot_info(self, depot_id, manifest_gid):
        with lock:
            self.app_info[depot_id] = manifest_gid

    def save_user_info(self):
        with lock:
            self.user_info.dump()

    def save(self):
        self.save_depot_info()
        self.save_user_info()

    def save_depot_info(self):
        with lock:
            self.app_info.dump()

    def get_app_worktree(self):
        worktree_dict = {}
        with lock:
            worktree_list = self.repo.git.worktree('list').split('\n')
        for worktree in worktree_list:
            path, head, name, *_ = worktree.split()
            name = name[1:-1]
            if not name.isdecimal():
                continue
            worktree_dict[name] = (path, head)
        return worktree_dict

    def get_remote_head(self):
        if self.remote_head:
            return self.remote_head
        head_dict = {}
        for i in self.repo.git.ls_remote('--head', 'origin').split('\n'):
            commit, head = i.split()
            head = head.split('/')[2]
            head_dict[head] = commit
        self.remote_head = head_dict
        return head_dict

    def check_app_repo_remote(self, repo):
        return str(repo) in self.get_remote_head()

    def check_app_repo_local(self, repo):
        for branch in self.repo.heads:
            if branch.name == str(repo):
                return True
        return False

    def get_remote_tags(self):
        if not self.tags:
            for i in filter(None, self.repo.git.ls_remote('--tags').split('\n')):
                sha, tag = i.split()
                tag = tag.split('/')[-1]
                self.tags.add(tag)
        return self.tags

    def check_manifest_exist(self, depot_id, manifest_gid):
        for tag in set([i.name for i in self.repo.tags] + [*self.tags]):
            if f'{depot_id}_{manifest_gid}' == tag:
                return True
        return False

    def init_app_repo(self, app_id):
        app_path = self.ROOT / f'depots/{app_id}'
        if str(app_id) not in self.get_app_worktree():
            if app_path.exists():
                app_path.unlink(missing_ok=True)
            if self.check_app_repo_remote(app_id):
                with lock:
                    if not self.check_app_repo_local(app_id):
                        self.repo.git.fetch('origin', f'{app_id}:origin_{app_id}')
                self.repo.git.worktree('add', '-b', app_id, app_path, f'origin_{app_id}')
            else:
                if self.check_app_repo_local(app_id):
                    self.log.warning(f'Branch {app_id} does not exist locally and remotely!')
                    self.repo.git.branch('-d', app_id)
                self.repo.git.worktree('add', '-b', app_id, app_path, 'app')

    def retry(self, fun, *args, retry_num=-1, **kwargs):
        while retry_num:
            try:
                return fun(*args, **kwargs)
            except gevent.timeout.Timeout as e:
                retry_num -= 1
                self.log.warning(e)
            except Exception as e:
                self.log.error(e)
                return

    def login(self, steam, username, password):
        self.log.info(f'Logging in to account {username}!')
        shared_secret = self.two_factor.get(username)
        steam.username = username
        result = steam.relogin()
        wait = 1
        if result != EResult.OK:
            if result != EResult.Fail:
                self.log.warning(f'User {username}: Relogin failure reason: {result.__repr__()}')
            if result == EResult.RateLimitExceeded:
                with lock:
                    time.sleep(wait)
            result = steam.login(username, password, steam.login_key, two_factor_code=generate_twofactor_code(
                base64.b64decode(shared_secret)) if shared_secret else None)
        count = self.retry_num
        while result != EResult.OK and count:
            if self.cli:
                with lock:
                    self.log.warning(f'Using the command line to interactively log in to account {username}!')
                    result = steam.cli_login(username, password)
                break
            elif result == EResult.RateLimitExceeded:
                if not count:
                    break
                with lock:
                    time.sleep(wait)
                result = steam.login(username, password, steam.login_key, two_factor_code=generate_twofactor_code(
                    base64.b64decode(shared_secret)) if shared_secret else None)
            elif result in (EResult.AccountLogonDenied, EResult.AccountDisabled,
                            EResult.AccountLoginDeniedNeedTwoFactor, EResult.PasswordUnset,
                            EResult.InvalidPassword):
                logging.warning(f'User {username} has been disabled!')
                self.user_info[username]['enable'] = False
                self.user_info[username]['status'] = result
                break
            wait += 1
            count -= 1
            self.log.error(f'User {username}: Login failure reason: {result.__repr__()}')
        if result == EResult.OK:
            self.log.info(f'User {username} login successfully!')
        else:
            self.log.error(f'User {username}: Login failure reason: {result.__repr__()}')
        return result

    def async_task(self, cdn, app_id, depot_id, manifest_gid):
        self.init_app_repo(app_id)
        manifest_path = self.ROOT / f'depots/{app_id}/{depot_id}_{manifest_gid}.manifest'
        if manifest_path.exists():
            self.log.debug(f'manifest_path exists: {manifest_path}')
            app_repo = git.Repo(self.ROOT / f'depots/{app_id}')
            try:
                manifest_commit = app_repo.git.rev_list('-1', str(app_id),
                                                        f'{depot_id}_{manifest_gid}.manifest').strip()
            except git.exc.GitCommandError:
                manifest_path.unlink(missing_ok=True)
            else:
                self.log.debug(f'manifest_commit: {manifest_commit}')
                return Result(result=True, app_id=app_id, depot_id=depot_id, manifest_gid=manifest_gid,
                              manifest_commit=manifest_commit)
        return get_manifest(cdn, app_id, depot_id, manifest_gid, True, self.ROOT, self.retry_num)

    def get_manifest(self, username, password, sentry_name=None):
        with lock:
            if username not in self.user_info:
                self.user_info[username] = {}
                self.user_info[username]['app'] = []
            if 'update' not in self.user_info[username]:
                self.user_info[username]['update'] = 0
            if 'enable' not in self.user_info[username]:
                self.user_info[username]['enable'] = True
            if not self.user_info[username]['enable']:
                logging.warning(f'User {username} is disabled!')
                return
        t = self.user_info[username]['update'] + self.update_wait_time - time.time()
        if t > 0:
            logging.warning(f'User {username} interval from next update: {int(t)}s!')
            return
        sentry_path = None
        if sentry_name:
            sentry_path = Path(
                self.credential_location if self.credential_location else MySteamClient.credential_location) / sentry_name
        self.log.debug(f'User {username} sentry_path: {sentry_path}')
        steam = MySteamClient(str(self.credential_location), sentry_path)
        result = self.login(steam, username, password)
        if result != EResult.OK:
            return
        self.log.info(f'User {username}: Waiting to initialize the cdn client!')
        cdn = self.retry(MyCDNClient, steam, retry_num=self.retry_num)
        if not cdn:
            logging.error(f'User {username}: Failed to initialize cdn!')
            return
        app_id_list = []
        if cdn.packages_info:
            self.log.info(f'User {username}: Waiting to get packages info!')
            product_info = self.retry(steam.get_product_info, packages=cdn.packages_info, retry_num=self.retry_num)
            if not product_info:
                logging.error(f'User {username}: Failed to get packages info!')
                return
            if cdn.packages_info:
                for package_id, info in product_info['packages'].items():
                    if 'depotids' in info and info['depotids'] and info['billingtype'] in BillingType.PaidList:
                        app_id_list.extend(list(info['appids'].values()))
        self.log.info(f'User {username}: {len(app_id_list)} paid app found!')
        if not app_id_list:
            self.user_info[username]['enable'] = False
            self.user_info[username]['status'] = result
            logging.warning(f'User {username}: Does not have any app and has been disabled!')
            return
        self.log.debug(f'User {username}, paid app id list: ' + ','.join([str(i) for i in app_id_list]))
        self.log.info(f'User {username}: Waiting to get app info!')
        fresh_resp = self.retry(steam.get_product_info, app_id_list, retry_num=self.retry_num)
        if not fresh_resp:
            logging.error(f'User {username}: Failed to get app info!')
            return
        job_list = []
        flag = True
        for app_id in app_id_list:
            if self.update_app_id_list and int(app_id) not in self.update_app_id_list:
                continue
            with lock:
                if int(app_id) in self.app_lock:
                    continue
                self.log.debug(f'Lock app: {app_id}')
                self.app_lock[int(app_id)] = set()
            app = fresh_resp['apps'][app_id]
            if 'common' in app and app['common']['type'].lower() in ['game', 'dlc', 'application']:
                if 'depots' not in fresh_resp['apps'][app_id]:
                    continue
                for depot_id, depot in fresh_resp['apps'][app_id]['depots'].items():
                    with lock:
                        self.app_lock[int(app_id)].add(depot_id)
                    if 'manifests' in depot and 'public' in depot['manifests'] and int(
                            depot_id) in {*cdn.licensed_depot_ids, *cdn.licensed_app_ids}:
                        manifest_gid = depot['manifests']['public']['gid']
                        self.set_depot_info(depot_id, manifest_gid)
                        with lock:
                            if int(app_id) not in self.user_info[username]['app']:
                                self.user_info[username]['app'].append(int(app_id))
                            if self.check_manifest_exist(depot_id, manifest_gid):
                                self.log.info(f'Already got the manifest: {depot_id}_{manifest_gid}')
                                continue
                        flag = False
                        job = gevent.Greenlet(LogExceptions(self.async_task), cdn, app_id, depot_id, manifest_gid)
                        job.rawlink(
                            functools.partial(self.get_manifest_callback, username, app_id, depot_id, manifest_gid))
                        job_list.append(job)
                        gevent.idle()
                for job in job_list:
                    job.start()
            with lock:
                if int(app_id) in self.app_lock and not self.app_lock[int(app_id)]:
                    self.log.debug(f'Unlock app: {app_id}')
                    self.app_lock.pop(int(app_id))
        with lock:
            if flag:
                self.user_info[username]['update'] = int(time.time())
        gevent.joinall(job_list)

    def run(self, update=False):
        if not self.account_info or self.init_only:
            self.save()
            self.account_info.dump()
            return
        if update and not self.update_user_list:
            self.update()
            if not self.update_user_list:
                return
        with Pool(self.pool_num) as pool:
            pool: ThreadPool
            result_list = []
            for username in self.account_info:
                if self.update_user_list and username not in self.update_user_list:
                    self.log.debug(f'User {username} has skipped the update!')
                    continue
                password, sentry_name = self.account_info[username]
                result_list.append(
                    pool.apply_async(LogExceptions(self.get_manifest), (username, password, sentry_name)))
            try:
                while pool._state == 'RUN':
                    if all([result.ready() for result in result_list]):
                        self.log.info('The program is finished and will exit in 10 seconds!')
                        time.sleep(10)
                        break
                    self.save()
                    time.sleep(1)
            except KeyboardInterrupt:
                with lock:
                    pool.terminate()
                os._exit(0)
            finally:
                self.save()

    def update(self):
        app_id_list = []
        for user, info in self.user_info.items():
            if info['enable']:
                if info['app']:
                    app_id_list.extend(info['app'])
        app_id_list = list(set(app_id_list))
        logging.debug(app_id_list)
        steam = MySteamClient(str(self.credential_location))
        self.log.info('Logging in to anonymous!')
        steam.anonymous_login()
        self.log.info('Waiting to get all app info!')
        app_info_dict = {}
        count = 0
        while app_id_list[count:count + 300]:
            fresh_resp = self.retry(steam.get_product_info, app_id_list[count:count + 300],
                                    retry_num=self.retry_num, timeout=60)
            count += 300
            if fresh_resp:
                for app_id, info in fresh_resp['apps'].items():
                    if depots := info.get('depots'):
                        app_info_dict[int(app_id)] = depots
                self.log.info(f'Acquired {len(app_info_dict)} app info!')
        update_app_set = set()
        for app_id, app_info in app_info_dict.items():
            for depot_id, depot in app_info.items():
                if depot_id.isdecimal():
                    if manifests := depot.get('manifests'):
                        if manifest := manifests.get('public'):
                            if depot_id in self.app_info and self.app_info[depot_id] != manifest:
                                update_app_set.add(app_id)
        update_app_user = {}
        update_user_set = set()
        for user, info in self.user_info.items():
            if info['enable'] and info['app']:
                for app_id in info['app']:
                    if int(app_id) in update_app_set:
                        if int(app_id) not in update_app_user:
                            update_app_user[int(app_id)] = []
                        update_app_user[int(app_id)].append(user)
                        update_user_set.add(user)
        self.log.debug(str(update_app_user))
        for user in self.account_info:
            if user not in self.user_info:
                update_user_set.add(user)
        self.update_user_list.extend(list(update_user_set))
        for app_id, user_list in update_app_user.items():
            self.log.info(f'{app_id}: {",".join(user_list)}')
        self.log.info(f'{len(update_app_user)} app and {len(self.update_user_list)} users need to update!')
        return self.update_user_list


if __name__ == '__main__':
    args = parser.parse_args()
    ManifestAutoUpdate(args.credential_location, level=args.level, pool_num=args.pool_num, retry_num=args.retry_num,
                       update_wait_time=args.update_wait_time, key=args.key, init_only=args.init_only,
                       cli=args.cli, app_id_list=args.app_id_list, user_list=args.user_list).run(update=args.update)
    if not args.no_push:
        if not args.init_only:
            push()
        push_data()
