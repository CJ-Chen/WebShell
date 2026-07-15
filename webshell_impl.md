# Web远程计算工作空间平台实现方案（无Docker版）

## 1. 项目目标

建设一个轻量化科研计算平台，实现：

* 用户通过网页注册/登录；
* 每个用户拥有独立工作空间；
* 浏览器直接访问Linux远程终端；
* 支持多终端管理；
* 支持网页文件上传、下载和管理；
* 所有用户通过统一网页入口访问；
* 服务器仅开放一个Web端口；
* 无需Docker，基于Linux原生用户体系运行。

最终用户体验：

```
浏览器
  ↓
登录
  ↓
进入个人空间
  ↓
Terminal运行Linux命令
  ↓
文件上传下载
  ↓
开展计算任务
```

---

# 2. 总体架构

```
                  用户浏览器

                       |
                       |
                    HTTPS 443

                       |

                 Nginx反向代理

                       |

              Web Workspace系统

                       |

       ---------------------------------

       |              |                |

   用户认证       Web Terminal      文件管理

       |              |                |

    SQLite        WebSocket        文件API

                       |

                Linux系统用户

                       |

       ---------------------------------

       |              |                |

    user001       user002          user003

    /home/user001 /home/user002   /home/user003

```

---

# 3. 核心设计原则

## 3.1 不使用Docker

原因：

* 部署简单；
* 更适合科研服务器/HPC环境；
* 直接使用Linux权限体系；
* GPU、软件环境管理更加直接；
* 避免容器维护成本。

---

## 3.2 Web账号与Linux账号绑定

采用：

```
网页账号
    |
    |
用户认证数据库
    |
    |
Linux系统用户
    |
    |
/home/用户名
```

每个用户拥有真实Linux身份。

例如：

```
网页用户：

zhangsan


对应Linux：

zhangsan


目录：

/home/zhangsan

```

---

# 4. 用户认证系统

## 4.1 用户注册

用户填写：

```
用户名
邮箱
密码
单位信息
邀请码（可选）
```

后台流程：

1. 检查用户名是否存在；
2. 使用Argon2/bcrypt加密密码；
3. 写入用户数据库；
4. 自动创建Linux用户；
5. 创建个人目录。

示例：

```bash
useradd -m zhangsan
```

生成：

```
/home/zhangsan
```

设置权限：

```bash
chmod 700 /home/zhangsan
```

---

## 4.2 用户数据库

推荐SQLite：

```
users

id
username
email
password_hash
linux_username
home_directory
quota
status
created_time

```

---

## 4.3 登录流程

用户输入：

```
用户名
密码
```

系统：

```
查询用户数据库

↓

验证密码Hash

↓

生成Session

↓

进入个人空间

```

---

# 5. Web Terminal系统

## 5.1 技术方案

浏览器：

```
xterm.js
```

通过：

```
WebSocket
```

连接：

```
后台Terminal服务
```

启动：

```
Linux bash
```

结构：

```
浏览器

 xterm.js

    |

 WebSocket

    |

 Terminal Backend

    |

 bash

    |

 Linux用户

```

---

## 5.2 终端保持

采用：

```
tmux
```

管理终端。

例如：

用户创建：

```
Terminal-001
```

后台：

```
tmux session:

zhangsan-terminal001

```

关闭网页：

任务继续运行。

重新登录：

恢复：

```
tmux attach

```

---

# 6. 文件管理系统

## 6.1 功能

右侧提供类似FTP的网页文件管理：

支持：

* 文件浏览；
* 上传；
* 下载；
* 删除；
* 重命名；
* 新建目录；
* 在线查看。

---

## 6.2 文件目录设计

服务器：

```
/home

├── zhangsan

│    ├── project

│    ├── upload

│    └── result

│

├── lisi

│    ├── project

│    └── result

```

Linux权限保证：

```
用户只能访问自己的目录
```

---

# 7. 用户工作空间界面设计

采用三栏布局：

```
------------------------------------------------

 用户：zhangsan


------------------------------------------------

| Terminal列表 | Terminal窗口 | 文件管理 |
|-------------|-------------|---------|
|             |             |         |
| bash-001    | $ ls        | upload |
| bash-002    | $ bwa       | result |
|             |             | data   |
| +新建终端   |             |         |

------------------------------------------------

```

---

# 8. 管理后台

管理员功能：

## 用户管理

支持：

* 创建用户；
* 删除用户；
* 禁用用户；
* 重置密码；
* 查看空间使用。

用户列表：

```
用户名       状态       空间

zhangsan    正常       100GB

lisi        禁用       500GB

```

---

## 资源限制

使用Linux quota：

例如：

```
zhangsan:

100GB

```

查看：

```bash
quota -u zhangsan
```

---

# 9. 推荐技术栈

## 前端

```
React

Ant Design

xterm.js

```

---

## 后端

```
Python FastAPI

```

负责：

* 用户认证；
* Session管理；
* Terminal创建；
* 文件API；
* 用户权限控制。

---

## 数据库

初期：

```
SQLite
```

后期：

```
PostgreSQL
```

---

## Web服务

```
Nginx
```

统一入口：

```
https://server.com
```

---

# 10. 推荐软件组件

## Web Terminal

```
ttyd
或者

xterm.js + WebSocket后端
```

---

## 文件管理

```
File Browser
```

---

## 任务保持

```
tmux
```

---

# 11. 部署方式

服务器要求：

```
Ubuntu 22.04/24.04

Python3

Nginx

tmux

```

安装完成后：

启动：

```
systemctl start workspace
```

用户访问：

```
https://服务器地址
```

即可。

---

# 12. 安全设计

## 网络

只开放：

```
443 HTTPS端口
```

关闭：

```
22 SSH公网访问
```

---

## 用户隔离

依靠：

```
Linux用户权限

chmod 700

文件属主控制

```

---

## 密码安全

采用：

```
Argon2

或者

bcrypt

```

禁止保存明文密码。

---

# 13. 后续扩展方向

## 计算任务管理

增加：

```
任务提交

任务队列

运行状态

结果管理

```

---

## 生信环境

预装：

```
conda

Python

R

BWA

SAMtools

GATK

BLAST

```

---

## AI能力

终端接入：

```
Qwen

DeepSeek

Codex

AI分析助手

```

---

## 集群扩展

未来可接：

```
Slurm

LDAP

Kubernetes

```

---

# 14. 最终推荐架构

```
Nginx

    |

FastAPI

    |

-----------------------------

|          |               |

Auth    Terminal       FileManager

|          |               |

SQLite    tmux        Linux filesystem


             |

        Linux users


             |

      /home/user空间

```

---

# 15. 总结

该方案实现：

* 一个网页入口；
* 一个443端口；
* 多用户账号体系；
* 独立Linux工作空间；
* 浏览器Terminal；
* 网页文件管理；
* 无Docker依赖；
* 简单部署；
* 支持后续扩展为科研计算云平台。

适合作为：

* 基因组分析平台；
* 育种计算平台；
* 实验室共享服务器入口；
* AI辅助科研计算环境。
