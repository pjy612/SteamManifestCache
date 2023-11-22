import git
import time
import logging
import argparse
import requests
from tqdm import tqdm


class Pr:
    log = logging.getLogger('Pr')

    def __init__(self, repo='.', source_repo=None, token=None, level=None):
        if level:
            level = logging.getLevelName(level.upper())
        else:
            level = logging.INFO
        logging.basicConfig(format='%(asctime)s - %(pathname)s[line:%(lineno)d] - %(levelname)s: %(message)s',
                            level=level)
        self.tqdm = None
        self.repo = git.Repo(repo)
        self.source_repo = source_repo
        self.add_source_repo()
        self.headers = {'Accept': 'application/vnd.github+json',
                        'Authorization': f'Bearer {token}', 'X-GitHub-Api-Version': '2022-11-28'}
        self.owner_name, self.repo_name = self.repo.remote().url.split('/')[-2:]
        self.source_owner_name, self.source_repo_name = self.repo.remote('source').url.split('/')[-2:]
        self.origin_app_list, self.origin_tag_list = self.get_refs_list()
        self.source_app_list, self.source_tag_list = self.get_refs_list(source_repo)
        self.local_app_list = [int(i.name) for i in self.repo.heads if i.name.isdecimal()]
        self.diff_app_set = set()
        self.pr_list = []

    def get_all_pr(self):
        if self.pr_list:
            return self.pr_list
        pr_list = []
        page = 1
        while True:
            url = f'https://api.github.com/repos/{self.source_owner_name}/{self.source_repo_name}/pulls?per_page=100&page={page}'
            r = requests.get(url, headers=self.headers)
            if not r.json():
                break
            pr_list.extend(r.json())
            page += 1
        self.pr_list = pr_list
        self.log.debug(str(self.pr_list))
        return self.pr_list

    def check_pr_exist(self, app_id):
        for pr in self.get_all_pr():
            if head := pr.get('head'):
                if label := head.get('label'):
                    if label == f'{self.source_owner_name}:{app_id}':
                        return True
        return False

    def add_source_repo(self):
        if not self.source_repo:
            return
        for i in self.repo.remotes:
            if i.name == 'source':
                return
        self.repo.git.remote('add', 'source', self.source_repo)

    def get_refs_list(self, repo=None):
        app_list = []
        tag_list = []
        if repo:
            result = self.repo.git.ls_remote(repo)
        else:
            result = self.repo.git.ls_remote()
        for i in result.split('\n'):
            if i:
                sha, refs = i.split()
                name = refs.split('/')[-1]
                if refs.startswith('refs/heads/'):
                    if name.isdecimal():
                        app_id = int(name)
                        app_list.append(app_id)
                elif refs.startswith('refs/tags/'):
                    if '_' in name:
                        tag_list.append(name)
        return app_list, tag_list

    def contains(self, tag):
        try:
            return self.repo.git.branch('-r', '--contains', tag).split('/')[-1]
        except git.exc.GitCommandError:
            pass

    def check_diff(self):
        for app_id in self.origin_app_list:
            if app_id not in self.source_app_list:
                self.diff_app_set.add(app_id)
        self.tqdm = tqdm(total=len(self.origin_tag_list))
        for tag in self.origin_tag_list:
            self.tqdm.set_postfix(tag=tag, refresh=False)
            if tag not in self.source_tag_list:
                if name := self.contains(tag):
                    if name.isdecimal():
                        app_id = int(name)
                        if app_id not in self.diff_app_set:
                            self.tqdm.set_postfix(tag=tag, app_id=app_id, refresh=False)
                            self.diff_app_set.add(app_id)
                else:
                    self.log.debug(f'Can\'t find the branch to which the tag belongs: {tag}')
            self.tqdm.update()

    def pr(self):
        self.check_diff()
        self.log.debug(str(self.diff_app_set))
        app_id_list = []
        for app_id in self.diff_app_set:
            if not self.check_pr_exist(app_id):
                self.log.info(f'app_id: {app_id}')
                app_id_list.append(app_id)
        self.log.debug(str(app_id_list))
        for app_id in app_id_list:
            url = f'https://api.github.com/repos/{self.source_owner_name}/{self.source_repo_name}/pulls'
            r = requests.post(url, headers=self.headers,
                              json={'title': str(app_id), 'head': f'{self.owner_name}:{app_id}', 'base': 'main'})
            if r.status_code == 201:
                self.log.info(f'pr successfully: {app_id}')
                time.sleep(15)
                continue
            self.log.info(f'pr failed: {app_id}, result: {r.text}, headers: {r.headers}')
            if r.status_code == 403 and 'x-ratelimit-reset' in r.headers:
                t = int(r.headers['x-ratelimit-reset'])
                now = int(time.time())
                if now < t:
                    count = t - now
                    self.log.info(f'Wait {count} second!')
                    while count:
                        time.sleep(1)
                        count -= 1
                        self.log.debug(f'Wait {count} second!')
            time.sleep(15)


parser = argparse.ArgumentParser()
parser.add_argument('-r', '--repo', default='https://github.com/BlankTMing/SteamManifestCache')
parser.add_argument('-t', '--token')
parser.add_argument('-l', '--level', default='INFO')

if __name__ == '__main__':
    args = parser.parse_args()
    Pr(source_repo=args.repo, token=args.token, level=args.level).pr()
