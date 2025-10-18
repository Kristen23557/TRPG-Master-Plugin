# TRPG-Master-Plugin
TRPG plugin for Maibot

TRPG 插件，让麦麦成为你的赛博DM/KP

🎲 一个功能完整的TRPG跑团插件，支持CoC和DnD双规则系统

https://img.shields.io/badge/License-MIT-blue.svg
https://img.shields.io/badge/Python-3.8+-green.svg
https://img.shields.io/badge/Support-CoC%2520%257C%2520DnD-orange.svg

✨ 特性亮点

🎯 双规则系统 - 完整支持CoC 7th和DnD 5e规则
🤖 智能剧情 - AI自动推进剧情发展
🎭 角色管理 - 完整的角色创建、存储、加载系统
⚔️ 战斗系统 - 回合制战斗，支持先攻排序
🎲 规则差异化 - CoC使用D100，DnD使用D20，完全不同的检定逻辑
📚 完善帮助 - 全局帮助系统和逐命令详细说明

🚀 快速部署

1、将插件文件放置到plugins目录
2、安装依赖
3、编辑 config.toml 文件进行基础配置：
auto_clean_days = 10              # 自动清理存档天数
plot_model = "Qwen/Qwen2.5-14B-Instruct"  # 剧情推进模型
api_url = "https://api.siliconflow.cn/v1/chat/completions"  # API地址
api_key = "your-api-key-here"     # 你的API密钥
temperature = 0.8                 # 生成随机性(0.0-1.0)
default_mode = "coc"              # 默认规则模式(coc/dnd)
max_players = 6                   # 最大玩家数
round_timeout = 120               # 回合超时时间(秒)
enable_auto_initiative = true     # 启用自动先攻
admin_users = ["123456789"]       # 管理员QQ号列表

剧本配置

准备剧本文件
创建 .txt 格式的剧本文件
放置在 plots/ 目录下
支持中文内容，建议包含完整的故事背景

🎮 使用指南
🆕 新手入门流程

1. 用户注册
bash
# 私聊机器人进行注册（保护隐私）
/register
💡 注册后会获得唯一UID，用于角色管理

2. 创建角色

# CoC角色示例（侦探）
/role create coc 张三 侦探 {str:60;con:70;dex:50;app:65;pow:75;siz:55;int:80;edu:85;luck:50}
# DnD角色示例（战士）  
/role create dnd 李四 战士 {力量:16;敏捷:14;体质:15;智力:10;感知:12;魅力:8}
📝 每个用户最多创建3个CoC角色和3个DnD角色

3. 开始游戏

# 团长开始剧本（需要先准备剧本文件）
/start coc plot=神秘庄园 roles=4
# 玩家加入剧本（使用剧本ID）
/join 123456
# 加载角色到当前剧本
/role load R12345

4. 开始冒险

# 进行技能检定
/check 侦查
/check 心理学
# 使用优势/劣势检定
/check 潜行 adv    # 优势检定
/check 格斗 dis    # 劣势检定
# 掷骰子
/dice D20
/dice D100
# 推进剧情（发送关键词）
推进剧情
继续故事
下一步

📚 完整命令手册
🎯 全局帮助
命令	说明	示例
/trpg	显示完整帮助菜单	/trpg
👤 用户管理
命令	说明	权限	示例
/register	用户注册	所有人	/register
🎭 角色管理
命令	说明	权限	示例
/role create	创建角色	已注册	/role create coc 名称 职业 {属性}
/role load	加载角色	已注册	/role load R12345
/role list	查看角色列表	已注册	/role list
/role view	查看角色详情	已注册	/role view R12345
/role delete	删除角色	角色所有者	/role delete R12345
/role help	角色命令帮助	所有人	/role help
📖 剧本管理
命令	说明	权限	示例
/start	开始新剧本	已注册	/start coc plot=剧本名
/join	加入剧本	已注册	/join 123456
/save	保存进度	团长/管理员	/save 存档名
[关键词]	推进剧情	剧本中	推进剧情
🎲 游戏命令
命令	说明	权限	示例
/check	进行检定	剧本中	/check 侦查
/dice	掷骰子	已注册	/dice D20
/combat	战斗管理	剧本中	/combat start
/npc	NPC管理	团长/管理员	/npc create 守卫 战士
/item	物品管理	团长/管理员	/item give 123456 药水

🐛 故障排除
常见问题
Q: 插件加载失败
A: 检查Python依赖是否安装完整，确认配置文件格式正确

Q: 剧本无法加载
A: 确认剧本文件为.txt格式，且放置在plots目录下

Q: 角色创建失败
A: 检查属性格式是否正确，属性值是否在有效范围内

Q: AI剧情不工作
A: 检查API配置是否正确，网络连接是否正常

查看全局帮助：
/trpg

📄 许可证
本项目采用MIT许可证，详见LICENSE文件。
