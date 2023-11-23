# Steam 清单仓库

## 项目简介

* 使用`Actions`自动爬取`Steam`游戏清单

## 项目结构

* `main`分支
    * `main.py`: 爬取清单主程序
        * `-c, --credential-location`: 存放账户凭据的路径,默认为`data/client`
        * `-l, --level`: 日志等级,默认为`INFO`
        * `-p, --pool-num`: 同时爬取账号数量,默认为`8`
        * `-r, --retry-num`: 失败或超时重试次数,默认为`3`
        * `-t, --update-wait-time`: 账号再次爬取间隔时间,单位秒,默认`86400`
        * `-k, --key`: 用于`users.json`解密的密钥
            * 提交远程仓库后如果重新克隆或使用`Actions`运行需要指定密钥才能解密
            * 手动解密: 把密钥保存到`KEY`文件,安装`git-crypt`,切换到data分支运行命令`git-crypt unlock KEY`
        * `-i, --init-only`: 仅初始化,不会去爬取清单
        * `-C, --cli`: 登录失败后会进入交互式登录
        * `-P, --no-push`: 阻止爬取完毕后自动push
        * `-u, --update`: 通过获取仓库所有app信息,来判断爬取的账号
        * `-a, --app-id`: 限定爬取的appid,可指定多个,空格分隔
        * `-U, --users`: 限定爬取的账号,可指定多个,空格分隔
    * `storage.py`: 使用清单一键入库
        * `-r, --repo`: 指定仓库
        * `-a, --app-id`: 游戏id
        * `-p, --app-path`: 导入本仓库app分支格式的目录
    * `apps.py`: 导出仓库所有游戏信息到`apps.xlsx`
        * `-r, --repo`: 指定仓库
        * `-o, --output`: 保存目录
    * `merge.py`: 用于`Actions`自动合并`pr`
        * `-t, --token`: 个人访问令牌
        * `-l, --level`: 日志等级,默认为`INFO`
    * `push.py`: 用于推送分支
    * `pr.py`: 用于pr分支
        * `-r, --repo`: 指定仓库
        * `-t, --token`: 个人访问令牌
* `data`分支: 用于存放账号数据,第一次运行程序初始化后会自动将其签出到`data`目录
    * `data/client`: 用于存放账号凭证文件和`cm`服务器信息的目录,需要将账号`ssfn`文件放在该目录
    * `data/users.json`: 用于存放账号和密码
        * 格式为: `{"账号": ["密码", "ssfnxxxx"], "账号": ["密码", null], ...}`
        * 没有`ssfn`需要填`null`
    * `data/appinfo.json`: 用于存放`appid`对应的`清单id`
        * 格式为: `{"11111": "清单id", ...}`
    * `data/userinfo.json`: 用于存放账户拥有的`appid`信息和是否被禁用等信息
        * 格式为: `{"账号": {"app": [11111, 22222, ...], "update": 1673018145, "enable": true, "status": 63}, ...}`
            * `update`: 上次更新时间戳
            * `enable`: 是否被禁用
            * `status`: 登录失败的原因 - [EResult](https://partner.steamgames.com/doc/api/steam_api#EResult)
    * `data/.gitattributes`: 记录`git-crypt`需要加密的文件
        * 默认加密: `users.json client/*.key 2fa.json`
    * `data/2fa.json`: 记录账号`2fa`信息
        * 格式: `{"账号": "shared_secret", ...}`
* 以`appid`为名称的分支: 该分支用于存放清单和密钥文件
    * `depots/xxx`: 程序运行后如果该`app`有新的清单会从远程拉取对应`appid`分支,不存在则会使用`main`分支的第一次提交创建一个空的`appid`分支,使用`worktree`
      将其签出到`depots/对应appid分支`目录,例如`depots/11111`
        * `depots/xxx/仓库id_清单id.manifest`: 清单文件
        * `config.vdf`: 密钥文件,其格式参考`Steam/config/config.vdf`
            * ```vdf
              "depots"
              {
                  "仓库id"
                  {
                      "DecryptionKey" "仓库密钥"
                  }
              }
              ```
* `tag`: 标记每一个的清单的提交
    * 命名格式: `仓库id_清单id`
    * 用于过滤已爬取的清单

## 运行流程

1. `.github/workflows/CI.yml`
    * 使用`Actions`定期爬取清单
2. 开启多线程同时登录多个账号爬取清单,直到所有账号都被爬取完毕
    * 判断账号是否禁用
    * 判断账号距离上次爬取时间是否大于可爬取间隔
    * 获取账号所有可爬取的清单，使用`tag`过滤已爬取的清单
3. 爬取结束后调用`push.py`上传`分支`和`tag`,并推送`data`分支

## 如何部署

1. fork本仓库(使用`Actions`初始化可跳过以下步骤)
2. 安装git,并配置你的`github`账号
3. 克隆你fork的仓库
    * `git clone https://github.com/你的名称/ManifestAutoUpdate --recurse-submodules --depth=1`
        * `--recurse-submodules`: 克隆子模块
        * `--depth=1`: 浅克隆
4. 安装依赖
    * `pip install -r requirements.txt`
5. 运行程序
    * `python main.py`
6. 初始化
    * 第一次运行程序会进行初始化操作
    * 初始化会生成`data`分支,使用`worktree`签出到`data`目录
    * 生成密钥用于加密`users.json`
        * 密钥生成路径位于: `data/KEY`
        * 同时程序会输出密钥的十六进制字符串,需要将其存放到github仓库密钥,名称保存为`KEY`
            * 打开你的仓库 -> `Settings` -> `Secrets` -> `Actions` -> `New repository secret`
            * 或者在你的仓库地址后面加上`/settings/secrets/actions/new`
    * 增加账号密码到`data/users.json`:
        * 之后如果需要使用`Actions`需要将其推送到远程仓库
            * 再次运行程序,程序结束时会自动推送到`data`分支
            * 手动推送步骤如下:
                1. `cd data`: 切换到`data`目录
                2. `git add -u`: 增加修改的内容
                3. `git commit -m "update"`: 提交修改
                4. `git push origin data`: 推送到远程`data`分支
7. Actions初始化和运行
    * 配置`workflow`读写权限: 仓库 -> `Settings` -> `Actions` -> `General` -> `Workflow permissions`
      -> `Read and write permissions`
    * 仓库打开`Actions`选择对应的`Workflow`点击`Run workflow`选择好参数运行
        * `INIT`: 初始化
            * `users`: 账号,可指定多个,逗号分隔
            * `password`: 密码,可指定多个,逗号分隔
            * `ssfn`: [ssfn](https://ssfnbox.com/),需要提前上传该文件到`credential_location`目录,可指定多个,逗号分隔
            * `2fa`: [shared_secret](https://zhuanlan.zhihu.com/p/28257212),可指定多个,逗号分隔
            * `update`: 是否更新账号
            * `update_users`: 需要更新的账号
            * 第一次初始化后记得保存密钥到仓库密钥,不然下次运行会因为没有密钥而报错,然后记得删除本次`Workflow`运行结果,防止密钥泄露,或者使用本地初始化更安全
        * `CI`: 爬取所有账号
        * `PR`: 自动`pr`清单到指定仓库
            * 由于`Github`
              禁止`Actions`[递归创建pr](https://docs.github.com/en/actions/using-workflows/triggering-a-workflow#triggering-a-workflow-from-a-workflow)
              ,所以需要创建一个[个人访问令牌](https://github.com/settings/tokens/new)保存到仓库密钥`GITHUB_TOKEN`
            * `repo`: 仓库地址
        * `MERGE`: 自动检查`pr`并合并清单
        * `UPDATE`: 加了`-u`参数

## 如何pr清单

* 本项目使用`Actions`定期检查并合并清单，是否合并成功请在`Actions`运行完后查看对应分支

1. 完成部署本项目并爬取清单
2. 打开你要`pr`清单的分支，点击`Compare & pull request`
3. 点击`Create pull request`创建`pr`

## Telegram交流群

* [SteamManifestShare](https://t.me/SteamManifestShare)

## 仓库游戏查看

1. [apps.xlsx](https://github.com/wxy1343/ManifestAutoUpdate/raw/data/apps.xlsx)
2. [在线查看](https://docs.google.com/spreadsheets/d/1tS-Tar11TAqnlaeh4c7kHJq-vHF8QiQ-EtcEy5NO8a8)