import git
import vdf
import shutil
import struct
import logging
import argparse
import requests
import traceback
from main import MyJson
from pathlib import Path
from binascii import crc32
from steam.core.manifest import DepotManifest


class Depot:

    def __init__(self, path, app_info=None, author=None):
        self.path = Path(path)
        self.repo = git.Repo(self.path)
        self.commit_list = self.get_all_commit()
        self.depot_key_dict = self.get_all_depot_key()
        self.depot_dict = self.get_all_manifest()
        self.app_info = app_info
        self.author = author

    def get_all_depot_key(self):
        depot_key_dict = dict()
        config_path = self.path / 'config.vdf'
        try:
            if config_path.exists():
                with config_path.open() as f:
                    config = vdf.load(f)
                if 'depots' in config and type(config['depots']) is dict:
                    for i, j in config['depots'].items():
                        if type(j) is dict and 'DecryptionKey' in j and j['DecryptionKey']:
                            depot_key_dict[int(i)] = j['DecryptionKey']
        except:
            traceback.print_exc()
        return depot_key_dict

    def get_all_commit(self, commit=None):
        commit_list = []
        if not commit:
            commit = self.repo.head.commit
        if commit:
            commit_list.append(commit)
        if commit.parents:
            commit_list.extend(self.get_all_commit(commit.parents[0]))
        return commit_list

    def get_manifest_author(self, manifest_name):
        if self.commit_list:
            for i in self.commit_list:
                if manifest_name in i.stats.files:
                    return i.author

    def get_all_manifest(self):
        depot_dict = dict()
        for i in self.path.iterdir():
            if i.suffix == '.manifest':
                try:
                    with i.open('rb') as f:
                        manifest = DepotManifest(f.read())
                    buffer = manifest.payload.SerializeToString()
                    crc_clear = crc32(struct.pack('<I', len(buffer)) + buffer)
                    if manifest.metadata.crc_clear != crc_clear:
                        manifest.metadata.crc_clear = crc_clear
                    depot_id = int(manifest.depot_id)
                    if depot_id in self.depot_key_dict:
                        depot_key = self.depot_key_dict[depot_id]
                        if len(depot_key) == 64:
                            author = self.get_manifest_author(i.name)
                            if author and author.name == 'github-actions[bot]':
                                author = None
                            depot_dict[depot_id] = (depot_key, manifest, i, author)
                except:
                    traceback.print_exc()
        return depot_dict

    def merge_depot_key(self, depot_id, depot_key):
        config_path = self.path / 'config.vdf'
        if config_path.exists():
            with config_path.open() as f:
                config = vdf.load(f)
        else:
            config = vdf.VDFDict()
        if 'depots' not in config:
            config['depots'] = {}
        depots = config['depots']
        if str(depot_id) not in depots:
            depots[str(depot_id)] = {'DecryptionKey': depot_key}
        with config_path.open('w') as f:
            vdf.dump(config, f, pretty=True)

    def merge(self, depot_id, manifest_gid, manifest_path, depot_key, author):
        author_name = None
        author_email = None
        if author:
            author_name = author.name
            author_email = author.email
        elif self.author:
            author_name = self.author.name
            author_email = self.author.email
        shutil.copy(manifest_path, self.path / f'{depot_id}_{manifest_gid}.manifest')
        self.merge_depot_key(depot_id, depot_key)
        self.repo.git.add(f'{depot_id}_{manifest_gid}.manifest')
        self.repo.git.add('config.vdf')
        if author_name:
            args = ['-c', f'user.name={author_name}']
            if author_email:
                args.extend(['-c', f'user.email={author_email}'])
            self.repo.git.execute(['git', *args, 'commit', '-m', f'Update depot: {depot_id}_{manifest_gid}'])
        else:
            self.repo.git.commit('-m', f'Update depot: {depot_id}_{manifest_gid}')
        self.repo.git.tag(f'{depot_id}_{manifest_gid}')
        if self.app_info:
            self.app_info[str(depot_id)] = manifest_gid

    def merge_depot(self, other):
        other: Depot
        for depot_id, args in other.depot_dict.items():
            depot_key_other, manifest_other, manifest_path_other, author_other = args
            try:
                if depot_id not in self.depot_dict:
                    self.merge(depot_id, manifest_other.gid, manifest_path_other, depot_key_other, author_other)
                else:
                    depot_key, manifest, manifest_path, author = self.depot_dict[depot_id]
                    if manifest.gid != manifest_other.gid:
                        if manifest.creation_time < manifest_other.creation_time:
                            manifest_path.unlink(missing_ok=True)
                            self.repo.git.add(manifest_path)
                            self.merge(depot_id, manifest_other.gid, manifest_path_other, depot_key_other, author_other)
            except:
                traceback.print_exc()


class Merge:
    ROOT = Path('data').absolute()
    log = logging.getLogger('Merge')
    app_info_path = ROOT / Path('appinfo.json')
    app_info = MyJson(app_info_path)

    def __init__(self, token, level=None):
        if level:
            level = logging.getLevelName(level.upper())
        else:
            level = logging.INFO
        logging.basicConfig(format='%(asctime)s - %(pathname)s[line:%(lineno)d] - %(levelname)s: %(message)s',
                            level=level)
        self.repo = git.Repo()
        self.remote_head_dict = self.get_remote_head()
        self.repo_url = '/'.join(self.repo.git.remote('get-url', 'origin').split('/')[-2:])
        self.headers = {'Accept': 'application/vnd.github+json',
                        'Authorization': f'Bearer {token}', 'X-GitHub-Api-Version': '2022-11-28'}
        self.pr_list = self.get_all_pr()
        self.local_heads = [i.name for i in self.repo.heads]
        self.author_name = None
        self.author_email = None

    def get_user_email(self):
        if not self.author_name:
            return
        url = f'https://api.github.com/users/{self.author_name}/events/public'
        r = requests.get(url, headers=self.headers)
        email_set = set()
        for i in r.json():
            if not (payload := i.get('payload')):
                continue
            if not (commits := payload.get('commits')):
                continue
            for commit in commits:
                if not (author := commit.get('author')):
                    continue
                if not (name := author.get('name')):
                    continue
                if name != self.author_name:
                    continue
                if not (email := author.get('email')):
                    continue
                email_set.add(email)
        if len(email_set) == 1:
            return email_set.pop()
        elif len(email_set) > 1:
            for i in email_set:
                if not i.endswith('@users.noreply.github.com'):
                    return i
            return email_set.pop()

    def get_remote_head(self):
        head_dict = {}
        for i in self.repo.git.ls_remote('--head', 'origin').split('\n'):
            commit, head = i.split()
            head = head.split('/')[2]
            head_dict[head] = commit
        return head_dict

    def get_all_pr(self):
        pr_list = []
        page = 1
        self.log.info('Getting pr list!')
        while True:
            url = f'https://api.github.com/repos/{self.repo_url}/pulls?per_page=100&page={page}'
            r = requests.get(url, headers=self.headers)
            if not r.json():
                break
            pr_list.extend(r.json())
            page += 1
        return pr_list

    def get_head(self, name):
        for i in self.repo.heads:
            if i.name == name:
                return i

    def merge(self, num, app_id):
        head_name = f'pr{app_id}'
        origin_head_name = f'origin_{head_name}'
        if origin_head_name not in self.local_heads:
            self.repo.git.fetch('origin', f'pull/{num}/head:{origin_head_name}')
        if head_name not in self.local_heads:
            self.repo.git.worktree('add', '-b', head_name, self.ROOT / 'depots' / head_name, origin_head_name)
        pr_repo = self.get_head(head_name)
        depot = Depot(self.ROOT / 'depots' / head_name, app_info=self.app_info)
        if app_id not in self.local_heads:
            if app_id in self.remote_head_dict:
                sha = self.remote_head_dict[app_id]
                if sha == pr_repo.commit.hexsha:
                    return
                if f'origin_{app_id}' not in self.local_heads:
                    self.repo.git.fetch('origin', f'{app_id}:origin_{app_id}')
                self.repo.git.worktree('add', '-b', app_id, self.ROOT / 'depots' / app_id, f'origin_{app_id}')
            else:
                self.repo.git.worktree('add', '-b', app_id, self.ROOT / 'depots' / app_id, 'app')
        source_depot = Depot(self.ROOT / 'depots' / app_id, app_info=self.app_info,
                             author=git.Actor(self.author_name, self.author_email))
        source_depot.merge_depot(depot)

    def close_pr(self, num):
        url = f'https://api.github.com/repos/{self.repo_url}/pulls/{num}'
        requests.patch(url, headers=self.headers, json={'state': 'closed'})

    def merge_all(self):
        for i in self.pr_list:
            try:
                num, app_id = i['number'], str(i['head']['ref'])
                if not app_id.isdecimal():
                    continue
                self.author_name = i['user']['login']
                user_id = i['user']['id']
                if self.author_name:
                    if not self.author_email:
                        self.author_email = self.get_user_email()
                    if not self.author_email:
                        self.author_email = f'{user_id}+{self.author_name}@users.noreply.github.com'
                self.log.info(
                    f'Merging pr {num} to appid {app_id} from {git.Actor(self.author_name, self.author_email).__repr__()}!')
                self.merge(num, app_id)
            except:
                traceback.print_exc()
            else:
                self.log.info(f'closing pr {num}!')
                self.close_pr(num)
        self.app_info.dump()


parser = argparse.ArgumentParser()
parser.add_argument('-t', '--token')
parser.add_argument('-l', '--level', default='INFO')

if __name__ == '__main__':
    args = parser.parse_args()
    Merge(token=args.token, level=args.level).merge_all()
