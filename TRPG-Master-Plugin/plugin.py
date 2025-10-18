# src/plugins/TRPG_Plugin/plugin.py
import os
import json
import random
import asyncio
import aiofiles
import aiohttp
import toml
from datetime import datetime, timedelta
from typing import List, Tuple, Type, Optional, Dict, Any
from pathlib import Path
import re

from src.plugin_system import (
    BasePlugin,
    register_plugin,
    BaseCommand,
    BaseAction,
    ComponentInfo,
    ConfigField,
    ActionActivationType,
    ChatMode
)
from src.plugin_system.apis import send_api, database_api

# --- 全局存储 ---
active_sessions = {}  # {session_id: session_data}
user_registry = {}    # {qq_number: uid}
character_db = {}     # {rid: character_data}
npc_db = {}           # {npc_id: npc_data}
combat_sessions = {}  # {session_id: combat_data}
save_db = {}          # {save_id: save_data}

# --- 常量定义 ---
PLUGIN_DIR = Path(__file__).parent.absolute()
SAVES_DIR = PLUGIN_DIR / "saves"
USERS_DIR = PLUGIN_DIR / "users" 
ROLES_DIR = PLUGIN_DIR / "roles"
PLOTS_DIR = PLUGIN_DIR / "plots"

# 创建必要目录
for directory in [SAVES_DIR, USERS_DIR, ROLES_DIR, PLOTS_DIR]:
    directory.mkdir(parents=True, exist_ok=True)

# 规则定义
RULES = {
    "coc": {
        "attributes": ["str", "con", "dex", "app", "pow", "siz", "int", "edu", "luck"],
        "skills": ["侦查", "图书馆使用", "心理学", "潜行", "格斗", "手枪", "闪避", "医学", "神秘学"],
        "check_types": ["力量检定", "敏捷检定", "智力检定", "意志检定"],
        "attribute_names": {
            "str": "力量", "con": "体质", "dex": "敏捷", "app": "外貌", 
            "pow": "意志", "siz": "体型", "int": "智力", "edu": "教育", "luck": "幸运"
        },
        "attribute_ranges": {
            "str": (15, 90), "con": (15, 90), "dex": (15, 90), "app": (15, 90),
            "pow": (15, 90), "siz": (15, 90), "int": (15, 90), "edu": (15, 90), "luck": (15, 90)
        }
    },
    "dnd": {
        "attributes": ["力量", "敏捷", "体质", "智力", "感知", "魅力"],
        "skills": ["运动", "潜行", "巧手", "奥秘", "历史", "调查", "自然", "宗教", "驯兽", "洞察", "医药", "察觉", "生存", "欺瞒", "威吓", "表演", "说服"],
        "check_types": ["力量检定", "敏捷检定", "体质检定", "智力检定", "感知检定", "魅力检定"],
        "attribute_names": {
            "力量": "力量", "敏捷": "敏捷", "体质": "体质", 
            "智力": "智力", "感知": "感知", "魅力": "魅力"
        },
        "attribute_ranges": {
            "力量": (8, 20), "敏捷": (8, 20), "体质": (8, 20),
            "智力": (8, 20), "感知": (8, 20), "魅力": (8, 20)
        }
    }
}

# === 工具函数 ===
def generate_session_id() -> str:
    """生成6位会话ID"""
    return str(random.randint(100000, 999999))

def generate_uid() -> str:
    """生成8位用户ID"""
    return str(random.randint(10000000, 99999999))

def generate_rid() -> str:
    """生成角色ID"""
    return f"R{random.randint(10000, 99999)}"

def generate_npc_id() -> str:
    """生成NPC ID"""
    return f"NPC{random.randint(1000, 9999)}"

def generate_save_id() -> str:
    """生成6位存档ID"""
    return str(random.randint(100000, 999999))

def load_user_registry():
    """加载用户注册表"""
    global user_registry
    user_registry = {}
    for file in USERS_DIR.glob("*.txt"):
        try:
            with open(file, 'r', encoding='utf-8') as f:
                data = json.load(f)
                user_registry[data['qq']] = data['uid']
        except:
            continue

def save_user_registry():
    """保存用户注册表"""
    for qq, uid in user_registry.items():
        file_path = USERS_DIR / f"{qq}{uid[-4:]}.txt"
        with open(file_path, 'w', encoding='utf-8') as f:
            json.dump({'qq': qq, 'uid': uid}, f, ensure_ascii=False)

def load_character_db():
    """加载角色数据库"""
    global character_db
    character_db = {}
    for file in ROLES_DIR.glob("*.json"):
        try:
            with open(file, 'r', encoding='utf-8') as f:
                data = json.load(f)
                character_db[data['rid']] = data
        except:
            continue

def save_character(character_data: Dict):
    """保存角色数据"""
    file_path = ROLES_DIR / f"{character_data['rid']}.json"
    with open(file_path, 'w', encoding='utf-8') as f:
        json.dump(character_data, f, ensure_ascii=False, indent=2)

def delete_character(rid: str):
    """删除角色数据"""
    file_path = ROLES_DIR / f"{rid}.json"
    if file_path.exists():
        file_path.unlink()
    if rid in character_db:
        del character_db[rid]

def load_save_db():
    """加载存档数据库"""
    global save_db
    save_db = {}
    for file in SAVES_DIR.glob("*.json"):
        try:
            with open(file, 'r', encoding='utf-8') as f:
                data = json.load(f)
                save_db[data['save_id']] = data
        except:
            continue

def save_save_data(save_data: Dict):
    """保存存档数据"""
    file_path = SAVES_DIR / f"{save_data['save_id']}.json"
    with open(file_path, 'w', encoding='utf-8') as f:
        json.dump(save_data, f, ensure_ascii=False, indent=2)

def delete_save(save_id: str):
    """删除存档"""
    file_path = SAVES_DIR / f"{save_id}.json"
    if file_path.exists():
        file_path.unlink()
    if save_id in save_db:
        del save_db[save_id]

async def load_plot_content(plot_name: str) -> Optional[str]:
    """加载剧本内容 - 仅支持txt文件"""
    plot_path = PLOTS_DIR / plot_name
    
    if not plot_path.exists():
        return None
        
    try:
        # 只支持txt文件
        if plot_path.suffix.lower() == '.txt':
            async with aiofiles.open(plot_path, 'r', encoding='utf-8') as f:
                return await f.read()
        else:
            return f"❌ 不支持的文件格式: {plot_path.suffix}，请使用.txt文件"
                
    except Exception as e:
        print(f"加载剧本失败 {plot_name}: {e}")
        return f"❌ 剧本文件读取失败: {str(e)}"

def get_available_plots() -> List[str]:
    """获取可用剧本列表 - 只显示txt文件"""
    return [f.name for f in PLOTS_DIR.glob("*.txt")]

def is_admin(user_id: str, plugin_instance) -> bool:
    """检查用户是否为管理员"""
    admin_users = plugin_instance.get_config("admin.admin_users", [])
    return str(user_id) in admin_users

def is_session_creator(user_id: str, session_id: str) -> bool:
    """检查用户是否为会话创建者"""
    if session_id in active_sessions:
        return str(active_sessions[session_id]['creator']) == str(user_id)
    return False

def check_user_registered(user_id: str) -> Tuple[bool, str]:
    """检查用户是否注册"""
    if str(user_id) not in user_registry:
        return False, "❌ 请先私聊机器人使用 `/register` 进行注册"
    return True, ""

def get_user_characters_count(user_id: str) -> Dict[str, int]:
    """获取用户角色数量统计"""
    user_uid = user_registry.get(str(user_id))
    if not user_uid:
        return {"coc": 0, "dnd": 0}
    
    coc_count = 0
    dnd_count = 0
    for character in character_db.values():
        if character.get("creator_uid") == user_uid:
            if character.get("mode") == "coc":
                coc_count += 1
            elif character.get("mode") == "dnd":
                dnd_count += 1
    return {"coc": coc_count, "dnd": dnd_count}

def validate_character_attributes(mode: str, attributes: Dict) -> Tuple[bool, str]:
    """验证角色属性是否符合规则"""
    rules = RULES.get(mode)
    if not rules:
        return False, f"未知模式: {mode}"
    
    # 检查必要属性
    required_attrs = rules["attributes"]
    for attr in required_attrs:
        if attr not in attributes:
            return False, f"缺少必要属性: {attr}"
    
    # 检查属性范围
    attribute_ranges = rules.get("attribute_ranges", {})
    for attr, value in attributes.items():
        if attr in attribute_ranges:
            min_val, max_val = attribute_ranges[attr]
            if not (min_val <= value <= max_val):
                return False, f"属性 {attr} 的值 {value} 超出范围 ({min_val}-{max_val})"
    
    return True, "验证通过"

def get_user_characters(user_id: str) -> List[Dict]:
    """获取用户的所有角色"""
    user_uid = user_registry.get(str(user_id))
    if not user_uid:
        return []
    
    user_characters = []
    for character in character_db.values():
        if character.get("creator_uid") == user_uid:
            user_characters.append(character)
    return user_characters

def get_user_saves_count(user_uid: str) -> int:
    """获取用户未完成存档数量"""
    count = 0
    for save_data in save_db.values():
        if save_data.get('creator_uid') == user_uid and save_data.get('status') == 'incomplete':
            count += 1
    return count

def get_user_saves_list(user_uid: str) -> List[Dict]:
    """获取用户的存档列表"""
    user_saves = []
    for save_data in save_db.values():
        if save_data.get('creator_uid') == user_uid and save_data.get('status') == 'incomplete':
            user_saves.append({
                'save_id': save_data['save_id'],
                'plot_name': save_data['plot_name'],
                'save_time': save_data['save_time'],
                'player_count': len(save_data.get('players', [])),
                'mode': save_data.get('mode', 'coc')
            })
    return user_saves

def generate_random_character(mode: str, name: str = "随机角色") -> Dict:
    """生成随机角色"""
    rid = generate_rid()
    attributes = {}
    
    if mode == "coc":
        for attr in RULES["coc"]["attributes"]:
            min_val, max_val = RULES["coc"]["attribute_ranges"][attr]
            attributes[attr] = random.randint(min_val, max_val)
    else:  # dnd
        for attr in RULES["dnd"]["attributes"]:
            min_val, max_val = RULES["dnd"]["attribute_ranges"][attr]
            attributes[attr] = random.randint(min_val, max_val)
    
    character_data = {
        "rid": rid,
        "name": name,
        "profession": "随机职业",
        "attributes": attributes,
        "creator_uid": "system",  # 系统生成的角色
        "mode": mode,
        "created_time": datetime.now().isoformat(),
        "hp": 100,
        "mp": 100 if mode == "coc" else 0,
        "status": "normal",
        "is_random": True  # 标记为随机生成的角色
    }
    
    # 保存角色
    character_db[rid] = character_data
    save_character(character_data)
    
    return character_data

# === 全局帮助命令 ===
class TRPGHelpCommand(BaseCommand):
    """TRPG全局帮助命令"""
    
    command_name = "trpg"
    command_description = "TRPG跑团插件全局帮助"
    command_pattern = r"^/trpg(?:\s+help)?$"
    intercept_message = True
    
    async def execute(self) -> Tuple[bool, Optional[str], bool]:
        """显示全局帮助菜单"""
        help_text = """🎲 **TRPG跑团插件全局帮助** 🎲

📚 **剧本管理:**
`/start <模式> plot=<剧本名> [roles=<人数>]` - 开始新剧本
`/load <存档ID>` - 加载存档继续游戏
`/join <剧本ID>` - 加入剧本
`/save` - 保存游戏进度
`/save list` - 查看我的存档

🎭 **角色管理:**
`/role create <模式> <角色名> [职业] {属性}` - 创建角色
`/role load <RID>` - 加载角色到当前剧本
`/role list` - 查看我的角色
`/role view <RID>` - 查看角色详情
`/role delete <RID>` - 删除角色
`/status` - 查看当前角色状态

🎲 **游戏命令:**
`/check <检定类型> [adv|dis]` - 进行检定
`/dice D<面数>` - 掷骰子
`/combat <动作> [目标]` - 战斗管理
`/npc <动作> [参数]` - NPC管理
`/item <动作> [参数]` - 物品管理

👤 **用户命令:**
`/register` - 用户注册（私聊使用）
`/plot list` - 查看可用剧本

🛠️ **团长命令:**
`/kick force <UID> [dr|sr]` - 踢出玩家
`/skip prepare` - 跳过准备阶段

💡 **规则说明:**
- CoC模式: 使用D100骰子，属性范围15-90
- DnD模式: 使用D20骰子，属性范围8-20
- 优势/劣势检定: adv/dis参数
- 每个用户最多3个CoC和3个DnD角色

📝 **提示:**
- 所有命令后加 `help` 查看详细帮助
- 剧本文件需为.txt格式放在plots目录
- 存档仅限团长和管理员操作"""
        await self.send_text(help_text)
        return True, "显示全局帮助", True

# === 角色管理命令 ===
class RoleCommand(BaseCommand):
    """角色管理命令"""
    
    command_name = "role"
    command_description = "角色创建和管理"
    command_pattern = r"^/role\s+(?P<action>\w+)(?:\s+(?P<params>.+))?$"
    intercept_message = True
    
    async def execute(self) -> Tuple[bool, Optional[str], bool]:
        try:
            user_id = self.message.message_info.user_info.user_id
            
            action = self.matched_groups.get("action", "")
            params = self.matched_groups.get("params", "")
            
            # 处理help参数 - 无需注册即可查看帮助
            if action == "help":
                return await self._show_help()
                
            # 检查用户注册（非help命令需要注册）
            registered, msg = check_user_registered(user_id)
            if not registered:
                await self.send_text(msg)
                return False, "用户未注册", True
                
            if action == "create":
                return await self._create_character(user_id, params)
            elif action == "load":
                return await self._load_character(user_id, params)
            elif action == "list":
                return await self._list_characters(user_id)
            elif action == "view":
                return await self._view_character(user_id, params)
            elif action == "delete":
                return await self._delete_character(user_id, params)
            else:
                await self.send_text("❌ 未知操作，使用 `/role help` 查看帮助")
                return False, "未知操作", True
                
        except Exception as e:
            await self.send_text(f"❌ 角色操作失败: {str(e)}")
            return False, f"角色操作失败: {str(e)}", True
    
    async def _create_character(self, user_id: str, params: str) -> Tuple[bool, Optional[str], bool]:
        """创建角色"""
        # 解析参数: 模式 角色名 职业 {属性}
        pattern = r'^(\S+)\s+(\S+)(?:\s+(\S+))?\s+\{([^}]+)\}$'
        match = re.match(pattern, params)
        
        if not match:
            await self.send_text("❌ 参数格式错误！请参考帮助")
            return False, "参数格式错误", True
            
        mode = match.group(1).lower()
        char_name = match.group(2)
        profession = match.group(3)
        attributes_str = match.group(4)
        
        # 验证模式
        if mode not in ["coc", "dnd"]:
            await self.send_text("❌ 模式错误！请使用 coc 或 dnd")
            return False, "模式错误", True
        
        # 检查角色数量限制
        user_counts = get_user_characters_count(user_id)
        max_per_mode = 3
        if user_counts[mode] >= max_per_mode:
            await self.send_text(f"❌ 您已经创建了 {user_counts[mode]} 个{mode.upper()}角色，每个模式最多只能创建{max_per_mode}个角色")
            return False, "角色数量超限", True
        
        # 解析属性
        attributes = {}
        for attr_pair in attributes_str.split(';'):
            if ':' in attr_pair:
                key, value = attr_pair.split(':', 1)
                attributes[key.strip()] = int(value.strip())
        
        # 验证属性
        is_valid, validation_msg = validate_character_attributes(mode, attributes)
        if not is_valid:
            await self.send_text(f"❌ 角色属性验证失败: {validation_msg}")
            return False, "属性验证失败", True
        
        # 创建角色
        rid = generate_rid()
        character_data = {
            "rid": rid,
            "name": char_name,
            "profession": profession or "无",
            "attributes": attributes,
            "creator_uid": user_registry[str(user_id)],
            "mode": mode,
            "created_time": datetime.now().isoformat(),
            "hp": 100,
            "mp": 100 if mode == "coc" else 0,
            "status": "normal"
        }
        
        # 保存角色
        character_db[rid] = character_data
        save_character(character_data)
        
        # 显示详细属性
        attr_display = "\n".join([f"  {RULES[mode]['attribute_names'].get(attr, attr)}: {value}" 
                                for attr, value in attributes.items()])
                
        await self.send_text(
            f"✅ **角色创建成功！**\n"
            f"🎭 名称: {char_name}\n"
            f"🏷️ 职业: {profession or '无'}\n"
            f"🆔 RID: {rid}\n"
            f"🎮 模式: {mode.upper()}\n"
            f"📊 属性详情:\n{attr_display}\n"
            f"💡 提示: 使用 `/role load {rid}` 将角色加载到剧本中"
        )
        
        return True, "角色创建成功", True
    
    async def _load_character(self, user_id: str, params: str) -> Tuple[bool, Optional[str], bool]:
        """加载角色到当前剧本"""
        rid = params.strip()
        
        if rid not in character_db:
            await self.send_text("❌ 角色ID不存在")
            return False, "角色不存在", True
            
        character = character_db[rid]
        
        # 检查权限
        if character["creator_uid"] != user_registry[str(user_id)]:
            await self.send_text("❌ 您不是该角色的创建者")
            return False, "权限不足", True
            
        # 查找用户当前会话
        current_session = None
        for session in active_sessions.values():
            for player in session["players"]:
                if player["qq"] == user_id:
                    current_session = session
                    break
            if current_session:
                break
                
        if not current_session:
            await self.send_text("❌ 您没有加入任何剧本")
            return False, "无可用会话", True
            
        # 检查模式匹配
        if character["mode"] != current_session["mode"]:
            await self.send_text(f"❌ 角色模式({character['mode'].upper()})与剧本模式({current_session['mode'].upper()})不匹配")
            return False, "模式不匹配", True
            
        # 关联角色
        for player in current_session["players"]:
            if player["qq"] == user_id:
                player["character_rid"] = rid
                player["ready"] = True  # 标记为准备就绪
                break
                
        # 显示详细属性
        mode = character["mode"]
        attr_display = "\n".join([f"  {RULES[mode]['attribute_names'].get(attr, attr)}: {value}" 
                                for attr, value in character['attributes'].items()])
                
        await self.send_text(
            f"✅ **角色加载成功！**\n"
            f"🎭 名称: {character['name']}\n"
            f"🏷️ 职业: {character.get('profession', '无')}\n"
            f"❤️ HP: {character['hp']}\n"
            f"📊 属性详情:\n{attr_display}"
        )
        
        # 检查是否所有玩家都准备就绪
        if current_session["status"] == "preparing":
            await self._check_all_ready(current_session)
        
        return True, "角色加载成功", True
    
    async def _check_all_ready(self, session: Dict):
        """检查是否所有玩家都准备就绪"""
        all_ready = all(player.get("ready", False) for player in session["players"])
        if all_ready:
            session["status"] = "playing"
            await self.send_text(
                f"🎉 **所有玩家准备就绪！**\n"
                f"游戏正式开始！\n\n"
                f"使用 `/check` 进行检定，发送剧情关键词推进故事"
            )
    
    async def _list_characters(self, user_id: str) -> Tuple[bool, Optional[str], bool]:
        """列出用户的所有角色"""
        user_characters = get_user_characters(user_id)
        
        if not user_characters:
            await self.send_text("📝 您还没有创建任何角色")
            return True, "无角色", True
            
        # 按模式分组
        coc_characters = [c for c in user_characters if c["mode"] == "coc"]
        dnd_characters = [c for c in user_characters if c["mode"] == "dnd"]
        
        character_list = "📋 **您的角色列表**\n\n"
        
        if coc_characters:
            character_list += "🐙 **CoC角色:**\n"
            for char in coc_characters:
                character_list += f"  • {char['name']} - RID: {char['rid']}\n"
            character_list += "\n"
        
        if dnd_characters:
            character_list += "🐉 **DnD角色:**\n"
            for char in dnd_characters:
                character_list += f"  • {char['name']} - RID: {char['rid']}\n"
        
        character_list += f"\n💡 使用 `/role view RID` 查看角色详情"
        
        await self.send_text(character_list)
        return True, "显示角色列表", True
    
    async def _view_character(self, user_id: str, params: str) -> Tuple[bool, Optional[str], bool]:
        """查看角色详情"""
        rid = params.strip()
        
        if rid not in character_db:
            await self.send_text("❌ 角色ID不存在")
            return False, "角色不存在", True
            
        character = character_db[rid]
        
        # 检查权限
        if character["creator_uid"] != user_registry[str(user_id)]:
            await self.send_text("❌ 您不是该角色的创建者")
            return False, "权限不足", True
        
        mode = character["mode"]
        attr_display = "\n".join([f"  {RULES[mode]['attribute_names'].get(attr, attr)}: {value}" 
                                for attr, value in character['attributes'].items()])
        
        # 构建角色详情
        detail_text = (
            f"🎭 **角色详情**\n\n"
            f"📝 名称: {character['name']}\n"
            f"🏷️ 职业: {character.get('profession', '无')}\n"
            f"🆔 RID: {character['rid']}\n"
            f"🎮 模式: {mode.upper()}\n"
            f"❤️ HP: {character['hp']}\n"
            f"🔮 MP: {character.get('mp', 0)}\n"
            f"📅 创建时间: {character['created_time'][:10]}\n\n"
            f"📊 **属性详情:**\n{attr_display}"
        )
        
        await self.send_text(detail_text)
        return True, "显示角色详情", True
    
    async def _delete_character(self, user_id: str, params: str) -> Tuple[bool, Optional[str], bool]:
        """删除角色"""
        rid = params.strip()
        
        if rid not in character_db:
            await self.send_text("❌ 角色ID不存在")
            return False, "角色不存在", True
            
        character = character_db[rid]
        
        # 检查权限
        if character["creator_uid"] != user_registry[str(user_id)]:
            await self.send_text("❌ 您不是该角色的创建者")
            return False, "权限不足", True
        
        # 检查角色是否正在使用
        for session in active_sessions.values():
            for player in session["players"]:
                if player.get("character_rid") == rid:
                    await self.send_text("❌ 该角色正在剧本中使用，无法删除")
                    return False, "角色正在使用", True
        
        # 删除角色
        character_name = character["name"]
        delete_character(rid)
        
        await self.send_text(f"✅ 已成功删除角色: {character_name} (RID: {rid})")
        return True, "角色删除成功", True
    
    async def _show_help(self) -> Tuple[bool, Optional[str], bool]:
        """显示角色帮助"""
        help_text = """🎭 **角色命令帮助**

**创建角色:**
`/role create <模式> <角色名> [职业] {属性列表}`
- 模式: coc 或 dnd
- 属性必须用花括号 {} 包围，属性间用分号 ; 分隔

**加载角色到剧本:**
`/role load <RID>`

**查看角色列表:**
`/role list`

**查看角色详情:**
`/role view <RID>`

**删除角色:**
`/role delete <RID>`

**📝 角色创建示例:**

**CoC角色示例:**
`/role create coc 张三 侦探 {str:60;con:70;dex:50;app:65;pow:75;siz:55;int:80;edu:85;luck:50}`

**DnD角色示例:**
`/role create dnd 李四 战士 {力量:16;敏捷:14;体质:15;智力:10;感知:12;魅力:8}`

**属性说明:**
- **CoC模式:** str(力量), con(体质), dex(敏捷), app(外貌), pow(意志), siz(体型), int(智力), edu(教育), luck(幸运)
  - 属性范围: 15-90

- **DnD模式:** 力量, 敏捷, 体质, 智力, 感知, 魅力
  - 属性范围: 8-20

**💡 提示:**
- 每个用户最多可创建3个CoC角色和3个DnD角色
- 创建角色无需加入剧本，但加载角色需要先加入剧本"""
        await self.send_text(help_text)
        return True, "显示帮助", True

# === 检定命令 ===
class CheckCommand(BaseCommand):
    """检定命令"""
    
    command_name = "check"
    command_description = "进行技能或属性检定"
    command_pattern = r"^/check\s+(?P<check_type>\S+)(?:\s+(?P<modifier>adv|dis|help))?$"
    intercept_message = True
    
    async def execute(self) -> Tuple[bool, Optional[str], bool]:
        try:
            user_id = self.message.message_info.user_info.user_id
            
            check_type = self.matched_groups.get("check_type", "")
            modifier = self.matched_groups.get("modifier", "")
            
            # 处理help参数
            if check_type == "help" or modifier == "help":
                return await self._show_help(user_id)
                
            # 检查用户注册（非help命令需要注册）
            registered, msg = check_user_registered(user_id)
            if not registered:
                await self.send_text(msg)
                return False, "用户未注册", True
                
            # 查找用户当前会话和角色
            current_session, character = await self._get_user_character(user_id)
            if not current_session or not character:
                await self.send_text("❌ 您没有在活跃的剧本中或有角色")
                return False, "无角色", True
                
            # 执行检定
            result = await self._perform_check(check_type, modifier, character, current_session["mode"])
            await self.send_text(result)
            
            return True, "检定完成", True
            
        except Exception as e:
            await self.send_text(f"❌ 检定失败: {str(e)}")
            return False, f"检定失败: {str(e)}", True
    
    async def _get_user_character(self, user_id: str) -> Tuple[Optional[Dict], Optional[Dict]]:
        """获取用户当前角色"""
        for session in active_sessions.values():
            for player in session["players"]:
                if player["qq"] == user_id and player["character_rid"]:
                    return session, character_db[player["character_rid"]]
        return None, None
    
    async def _perform_check(self, check_type: str, modifier: str, character: Dict, mode: str) -> str:
        """执行检定并返回详细结果 - 区分CoC和DnD规则"""
        attributes = character["attributes"]
        check_name = ""
        target_value = 0
        attribute_used = ""
        
        # 确定检定类型和目标值
        if check_type in attributes:
            # 直接属性检定
            target_value = attributes[check_type]
            check_name = f"{RULES[mode]['attribute_names'].get(check_type, check_type)}检定"
            attribute_used = RULES[mode]['attribute_names'].get(check_type, check_type)
        elif check_type in RULES[mode]["skills"]:
            # 技能检定
            if mode == "coc":
                # CoC技能检定：技能值就是目标值（简化处理）
                target_value = 50  # CoC技能基础值
                attribute_used = "技能基础值"
            else:
                # DnD技能检定：使用属性调整值 + 熟练加值
                base_attribute = self._get_dnd_skill_attribute(check_type)
                attr_value = attributes.get(base_attribute, 10)
                proficiency_bonus = 2  # 简化处理，固定熟练加值
                target_value = 10 + ((attr_value - 10) // 2) + proficiency_bonus
                attribute_used = base_attribute
            check_name = f"{check_type}检定"
        elif check_type in RULES[mode]["check_types"]:
            # 标准属性检定
            attr_map = {
                "力量检定": "str" if mode == "coc" else "力量",
                "敏捷检定": "dex" if mode == "coc" else "敏捷", 
                "体质检定": "con" if mode == "coc" else "体质",
                "智力检定": "int" if mode == "coc" else "智力",
                "意志检定": "pow",
                "感知检定": "感知",
                "魅力检定": "魅力"
            }
            if check_type in attr_map and attr_map[check_type] in attributes:
                target_value = attributes[attr_map[check_type]]
                check_name = check_type
                attribute_used = RULES[mode]['attribute_names'].get(attr_map[check_type], attr_map[check_type])
            else:
                return f"❌ 未知的检定类型: {check_type}"
        else:
            return f"❌ 未知的检定类型: {check_type}"
        
        # 根据模式执行不同的掷骰逻辑
        if mode == "coc":
            return await self._perform_coc_check(check_name, target_value, modifier, character, attribute_used)
        else:
            return await self._perform_dnd_check(check_name, target_value, modifier, character, attribute_used)
    
    def _get_dnd_skill_attribute(self, skill: str) -> str:
        """获取DnD技能对应的主要属性"""
        skill_attributes = {
            "运动": "力量",
            "潜行": "敏捷", "巧手": "敏捷",
            "奥秘": "智力", "历史": "智力", "调查": "智力", "自然": "智力", "宗教": "智力",
            "驯兽": "感知", "洞察": "感知", "医药": "感知", "察觉": "感知", "生存": "感知",
            "欺瞒": "魅力", "威吓": "魅力", "表演": "魅力", "说服": "魅力"
        }
        return skill_attributes.get(skill, "感知")
    
    async def _perform_coc_check(self, check_name: str, target_value: int, modifier: str, character: Dict, attribute_used: str) -> str:
        """执行CoC检定 - 使用D100骰子"""
        # CoC使用D100骰子
        roll_details = ""
        if modifier == "adv":
            roll1 = random.randint(1, 100)
            roll2 = random.randint(1, 100)
            roll_result = min(roll1, roll2)  # CoC优势取较小值
            roll_details = f"优势检定: 🎲{roll1} 和 🎲{roll2} → 取 **{roll_result}**"
        elif modifier == "dis":
            roll1 = random.randint(1, 100)
            roll2 = random.randint(1, 100)
            roll_result = max(roll1, roll2)  # CoC劣势取较大值
            roll_details = f"劣势检定: 🎲{roll1} 和 🎲{roll2} → 取 **{roll_result}**"
        else:
            roll_result = random.randint(1, 100)
            roll_details = f"检定结果: 🎲**{roll_result}**"
        
        # CoC结果分级
        if roll_result <= target_value // 5:
            result_level = "大成功"
            emoji = "🎉"
            description = "完美成功！获得额外奖励效果"
        elif roll_result <= target_value // 2:
            result_level = "困难成功" 
            emoji = "✅"
            description = "优秀表现，超出预期效果"
        elif roll_result <= target_value:
            result_level = "成功"
            emoji = "✓"
            description = "正常达成目标"
        elif roll_result <= 95:
            result_level = "失败"
            emoji = "❌"
            description = "未能达成目标"
        else:
            result_level = "大失败"
            emoji = "💥"
            description = "严重失败！可能带来额外负面效果"
        
        return (
            f"🎲 **{check_name}** {emoji} (CoC规则)\n"
            f"👤 角色: **{character['name']}**\n"
            f"📊 使用属性: **{attribute_used}** ({target_value})\n"
            f"🎯 {roll_details}\n"
            f"📈 目标值: **{target_value}**\n"
            f"📋 CoC难度分级:\n"
            f"  • 大成功: ≤ {target_value // 5}\n"
            f"  • 困难成功: ≤ {target_value // 2}\n"
            f"  • 成功: ≤ {target_value}\n"
            f"  • 失败: ≤ 95\n"
            f"  • 大失败: 96-100\n"
            f"🏆 结果: **{result_level}**\n"
            f"💬 {description}"
        )
    
    async def _perform_dnd_check(self, check_name: str, target_value: int, modifier: str, character: Dict, attribute_used: str) -> str:
        """执行DnD检定 - 使用D20骰子"""
        # DnD使用D20骰子
        roll_details = ""
        if modifier == "adv":
            roll1 = random.randint(1, 20)
            roll2 = random.randint(1, 20)
            roll_result = max(roll1, roll2)  # DnD优势取较大值
            roll_details = f"优势检定: 🎲{roll1} 和 🎲{roll2} → 取 **{roll_result}**"
        elif modifier == "dis":
            roll1 = random.randint(1, 20)
            roll2 = random.randint(1, 20)
            roll_result = min(roll1, roll2)  # DnD劣势取较小值
            roll_details = f"劣势检定: 🎲{roll1} 和 🎲{roll2} → 取 **{roll_result}**"
        else:
            roll_result = random.randint(1, 20)
            roll_details = f"检定结果: 🎲**{roll_result}**"
        
        # DnD结果判断
        total_roll = roll_result
        success = total_roll >= target_value
        
        result_level = "成功" if success else "失败"
        emoji = "✅" if success else "❌"
        description = "达成目标" if success else "未达成目标"
        
        return (
            f"🎲 **{check_name}** {emoji} (DnD规则)\n"
            f"👤 角色: **{character['name']}**\n"
            f"📊 使用属性: **{attribute_used}**\n"
            f"🎯 {roll_details}\n"
            f"📈 难度等级(DC): **{target_value}**\n"
            f"📋 DnD规则: 骰值 ≥ DC 即为成功\n"
            f"🏆 结果: **{result_level}**\n"
            f"💬 {description}"
        )
    
    async def _show_help(self, user_id: str) -> Tuple[bool, Optional[str], bool]:
        """显示检定帮助"""
        help_text = """🎲 **检定命令帮助**

**基础检定:**
`/check <检定类型>`
示例: `/check 侦查`

**优势/劣势检定:**
`/check <检定类型> adv` - 优势检定
`/check <检定类型> dis` - 劣势检定

**规则差异:**
- **CoC规则:** 使用D100骰子，优势取较小值，劣势取较大值
- **DnD规则:** 使用D20骰子，优势取较大值，劣势取较小值

**可用检定类型:**
- **属性检定:** 力量检定, 敏捷检定, 体质检定, 智力检定, 意志检定, 感知检定, 魅力检定
- **技能检定:** 侦查, 图书馆使用, 心理学, 潜行, 格斗, 手枪, 闪避, 医学, 神秘学等

**注意:** 需要在剧本中使用，且需要有角色"""
        await self.send_text(help_text)
        return True, "显示检定帮助", True

# === 开始剧本命令 ===
class StartCommand(BaseCommand):
    """开始新剧本命令"""
    
    command_name = "start"
    command_description = "开始新的跑团剧本"
    command_pattern = r"^/start\s+(?P<mode>\w+)\s+plot=(?P<plot>[\w\.\-]+)(?:\s+roles=(?P<roles>\d+))?(?:\s+help)?$"
    intercept_message = True
    
    async def execute(self) -> Tuple[bool, Optional[str], bool]:
        try:
            # 获取聊天流信息
            chat_stream = getattr(self, 'chat_stream', None)
            if chat_stream is None:
                # 尝试从message对象获取
                message_obj = getattr(self, 'message', None)
                if message_obj:
                    chat_stream = getattr(message_obj, 'chat_stream', None)
            
            if chat_stream is None:
                await self.send_text("❌ 无法获取聊天上下文信息")
                return False, "缺少聊天上下文", True
                
            user_id = self.message.message_info.user_info.user_id
            
            mode = self.matched_groups.get("mode", "").lower()
            
            # 处理help参数
            if mode == "help":
                return await self._show_help()
                
            # 检查用户注册（非help命令需要注册）
            registered, msg = check_user_registered(user_id)
            if not registered:
                await self.send_text(msg)
                return False, "用户未注册", True
                
            plot_name = self.matched_groups.get("plot", "")
            roles = int(self.matched_groups.get("roles", 4))
            
            if mode not in ["coc", "dnd"]:
                await self.send_text("❌ 模式错误！请使用 coc 或 dnd")
                return False, "模式错误", True
                
            # 检查剧本是否存在
            available_plots = get_available_plots()
            if plot_name not in available_plots:
                plot_list = "\n".join([f"- {plot}" for plot in available_plots])
                await self.send_text(
                    f"❌ 剧本 '{plot_name}' 不存在！\n\n"
                    f"📚 可用剧本列表:\n{plot_list}\n\n"
                    f"请将.txt剧本文件放入 {PLOTS_DIR} 目录"
                )
                return False, "剧本不存在", True
                
            # 加载剧本内容
            plot_content = await load_plot_content(plot_name)
            if not plot_content or plot_content.startswith("❌"):
                await self.send_text(f"❌ {plot_content or '剧本文件读取失败'}")
                return False, "剧本读取失败", True
                
            # 生成会话
            session_id = generate_session_id()
            stream_id = getattr(chat_stream, 'stream_id', 'unknown')
            
            active_sessions[session_id] = {
                "session_id": session_id,
                "mode": mode,
                "plot_name": plot_name,
                "plot_content": plot_content[:5000],
                "max_players": roles,
                "creator": user_id,
                "creator_uid": user_registry[str(user_id)],
                "stream_id": stream_id,
                "players": [],
                "npcs": [],
                "items": [],
                "status": "recruiting",
                "current_progress": "开始",
                "created_time": datetime.now().isoformat(),
                "last_activity": datetime.now().isoformat(),
                "is_new_game": True  # 标记为新游戏
            }
            
            # 发送召集消息
            await self.send_text(
                f"🎭 **新的{mode.upper()}剧本开始召集！**\n"
                f"📖 剧本: `{plot_name}`\n"
                f"📜 剧本ID: `{session_id}`\n"
                f"👥 玩家席位: {roles}人\n"
                f"⏰ 召集时间: 1分钟\n\n"
                f"请使用 `/join {session_id}` 加入游戏！"
            )
            
            # 设置定时器
            asyncio.create_task(self._start_session_after_delay(session_id))
            
            return True, f"开始{mode}剧本成功", True
            
        except Exception as e:
            await self.send_text(f"❌ 开始剧本失败: {str(e)}")
            return False, f"开始失败: {str(e)}", True
    
    async def _start_session_after_delay(self, session_id: str):
        """1分钟后自动开始剧本"""
        await asyncio.sleep(60)
        
        if session_id in active_sessions:
            session = active_sessions[session_id]
            if session["status"] == "recruiting":
                if len(session["players"]) > 0:
                    session["status"] = "preparing"
                    await self.send_text(
                        f"🎉 **剧本 {session_id} 进入准备阶段！**\n"
                        f"📖 剧本: {session['plot_name']}\n"
                        f"🎮 模式: {session['mode'].upper()}\n\n"
                        f"⏰ 准备阶段: 5分钟\n"
                        f"请各位玩家使用 `/role create` 创建角色或 `/role load` 加载已有角色\n"
                        f"使用 `/role help` 查看角色创建帮助\n\n"
                        f"团长可使用 `/skip prepare` 提前结束准备阶段"
                    )
                    
                    # 开始准备阶段倒计时
                    asyncio.create_task(self._start_preparing_phase(session_id))
                else:
                    await self.send_text("❌ 没有玩家加入，剧本自动取消")
                    del active_sessions[session_id]
    
    async def _start_preparing_phase(self, session_id: str):
        """开始准备阶段"""
        await asyncio.sleep(300)  # 5分钟
        
        if session_id in active_sessions:
            session = active_sessions[session_id]
            if session["status"] == "preparing":
                # 为没有角色的玩家生成随机角色
                for player in session["players"]:
                    if not player.get("character_rid"):
                        random_char = generate_random_character(session["mode"], f"玩家{player['qq']}")
                        player["character_rid"] = random_char["rid"]
                        player["ready"] = True
                        
                        # 发送随机角色信息
                        mode = session["mode"]
                        attr_display = "\n".join([f"  {RULES[mode]['attribute_names'].get(attr, attr)}: {value}" 
                                                for attr, value in random_char['attributes'].items()])
                        
                        await self.send_text(
                            f"🎲 **为玩家 {player['qq']} 生成了随机角色**\n"
                            f"🎭 名称: {random_char['name']}\n"
                            f"🏷️ 职业: {random_char['profession']}\n"
                            f"🆔 RID: {random_char['rid']}\n"
                            f"📊 属性详情:\n{attr_display}"
                        )
                
                session["status"] = "playing"
                await self.send_text(
                    f"⏰ **准备阶段结束！**\n"
                    f"游戏正式开始！\n\n"
                    f"使用 `/check` 进行检定，发送剧情关键词推进故事"
                )
    
    async def _show_help(self) -> Tuple[bool, Optional[str], bool]:
        """显示开始剧本帮助"""
        help_text = """🎭 **开始剧本命令帮助**

**使用方法:**
`/start <模式> plot=<剧本名> [roles=<人数>]`

**参数说明:**
- 模式: coc 或 dnd
- 剧本名: 剧本文件名（不含路径）
- 人数: 可选，玩家数量，默认4人

**示例:**
`/start coc plot=神秘庄园`
`/start dnd plot=龙之巢穴 roles=6`

**注意:**
- 需要先注册才能开始剧本
- 剧本文件必须是.txt格式，放在plots目录"""
        await self.send_text(help_text)
        return True, "显示开始剧本帮助", True

# === 加载存档命令 ===
class LoadCommand(BaseCommand):
    """加载存档命令"""
    
    command_name = "load"
    command_description = "加载存档继续游戏"
    command_pattern = r"^/load\s+(?P<save_id>\d{6})(?:\s+help)?$"
    intercept_message = True
    
    async def execute(self) -> Tuple[bool, Optional[str], bool]:
        try:
            save_id = self.matched_groups.get("save_id")
            
            # 处理help参数
            if save_id == "help":
                return await self._show_help()
                
            user_id = self.message.message_info.user_info.user_id
            
            # 检查用户注册
            registered, msg = check_user_registered(user_id)
            if not registered:
                await self.send_text(msg)
                return False, "用户未注册", True
            
            if save_id not in save_db:
                await self.send_text("❌ 存档ID不存在")
                return False, "存档不存在", True
                
            save_data = save_db[save_id]
            user_uid = user_registry[str(user_id)]
            
            # 检查权限：只有团长或管理员可以加载存档
            if save_data.get('creator_uid') != user_uid and not is_admin(user_id, self.plugin):
                await self.send_text("❌ 您不是该存档的创建者，无法加载")
                return False, "权限不足", True
            
            # 获取聊天流信息
            chat_stream = getattr(self, 'chat_stream', None)
            if chat_stream is None:
                message_obj = getattr(self, 'message', None)
                if message_obj:
                    chat_stream = getattr(message_obj, 'chat_stream', None)
            
            if chat_stream is None:
                await self.send_text("❌ 无法获取聊天上下文信息")
                return False, "缺少聊天上下文", True
                
            stream_id = getattr(chat_stream, 'stream_id', 'unknown')
            
            # 创建新会话
            session_id = generate_session_id()
            active_sessions[session_id] = {
                "session_id": session_id,
                "mode": save_data["mode"],
                "plot_name": save_data["plot_name"],
                "plot_content": save_data.get("plot_content", ""),
                "max_players": save_data.get("max_players", 4),
                "creator": user_id,
                "creator_uid": user_uid,
                "stream_id": stream_id,
                "players": [],
                "npcs": save_data.get("npcs", []),
                "items": save_data.get("items", []),
                "status": "recruiting",
                "current_progress": save_data.get("current_progress", "继续游戏"),
                "created_time": datetime.now().isoformat(),
                "last_activity": datetime.now().isoformat(),
                "is_new_game": False,  # 标记为加载存档
                "save_id": save_id,    # 关联的存档ID
                "original_players": save_data.get("players", [])  # 保存原始玩家数据
            }
            
            # 发送召集消息
            original_player_count = len(save_data.get("players", []))
            await self.send_text(
                f"💾 **加载存档继续游戏！**\n"
                f"📁 存档: `{save_id}`\n"
                f"📖 剧本: `{save_data['plot_name']}`\n"
                f"📜 剧本ID: `{session_id}`\n"
                f"🎮 模式: {save_data['mode'].upper()}\n"
                f"👥 原玩家数: {original_player_count}人\n"
                f"⏰ 召集时间: 1分钟\n\n"
                f"原玩家将自动匹配角色，新玩家可选择剩余角色\n"
                f"请使用 `/join {session_id}` 加入游戏！"
            )
            
            # 设置定时器
            asyncio.create_task(self._start_session_after_delay(session_id))
            
            return True, "加载存档成功", True
            
        except Exception as e:
            await self.send_text(f"❌ 加载存档失败: {str(e)}")
            return False, f"加载失败: {str(e)}", True
    
    async def _start_session_after_delay(self, session_id: str):
        """1分钟后自动开始准备阶段"""
        await asyncio.sleep(60)
        
        if session_id in active_sessions:
            session = active_sessions[session_id]
            if session["status"] == "recruiting":
                if len(session["players"]) > 0:
                    session["status"] = "preparing"
                    
                    # 自动为原玩家匹配角色
                    original_players = session.get("original_players", [])
                    current_players = session["players"]
                    
                    matched_count = 0
                    for current_player in current_players:
                        for original_player in original_players:
                            if current_player["uid"] == original_player.get("uid"):
                                if original_player.get("character_rid"):
                                    current_player["character_rid"] = original_player["character_rid"]
                                    current_player["ready"] = True
                                    matched_count += 1
                                    break
                    
                    await self.send_text(
                        f"🎉 **剧本 {session_id} 进入准备阶段！**\n"
                        f"📖 剧本: {session['plot_name']}\n"
                        f"🎮 模式: {session['mode'].upper()}\n"
                        f"🔗 自动匹配角色: {matched_count}人\n\n"
                        f"⏰ 准备阶段: 5分钟\n"
                        f"已自动匹配角色的玩家准备就绪\n"
                        f"其他玩家请使用 `/role load` 选择角色或创建新角色\n\n"
                        f"团长可使用 `/skip prepare` 提前结束准备阶段"
                    )
                    
                    # 开始准备阶段倒计时
                    asyncio.create_task(self._start_preparing_phase(session_id))
                else:
                    await self.send_text("❌ 没有玩家加入，剧本自动取消")
                    del active_sessions[session_id]
    
    async def _start_preparing_phase(self, session_id: str):
        """开始准备阶段"""
        await asyncio.sleep(300)  # 5分钟
        
        if session_id in active_sessions:
            session = active_sessions[session_id]
            if session["status"] == "preparing":
                # 为没有角色的玩家分配剩余角色或生成随机角色
                original_players = session.get("original_players", [])
                available_characters = []
                
                # 收集未被选择的原角色
                for original_player in original_players:
                    character_rid = original_player.get("character_rid")
                    if character_rid and character_rid not in [p.get("character_rid") for p in session["players"] if p.get("character_rid")]:
                        available_characters.append(character_rid)
                
                # 为没有角色的玩家分配角色
                for player in session["players"]:
                    if not player.get("character_rid"):
                        if available_characters:
                            # 分配剩余的原角色
                            character_rid = available_characters.pop(0)
                            player["character_rid"] = character_rid
                            player["ready"] = True
                            
                            character = character_db.get(character_rid, {})
                            await self.send_text(
                                f"🎭 **为玩家 {player['qq']} 分配了剩余角色**\n"
                                f"📝 名称: {character.get('name', '未知角色')}\n"
                                f"🆔 RID: {character_rid}"
                            )
                        else:
                            # 生成随机角色
                            random_char = generate_random_character(session["mode"], f"玩家{player['qq']}")
                            player["character_rid"] = random_char["rid"]
                            player["ready"] = True
                            
                            mode = session["mode"]
                            attr_display = "\n".join([f"  {RULES[mode]['attribute_names'].get(attr, attr)}: {value}" 
                                                    for attr, value in random_char['attributes'].items()])
                            
                            await self.send_text(
                                f"🎲 **为玩家 {player['qq']} 生成了随机角色**\n"
                                f"🎭 名称: {random_char['name']}\n"
                                f"🏷️ 职业: {random_char['profession']}\n"
                                f"🆔 RID: {random_char['rid']}\n"
                                f"📊 属性详情:\n{attr_display}"
                            )
                
                session["status"] = "playing"
                await self.send_text(
                    f"⏰ **准备阶段结束！**\n"
                    f"游戏继续！\n\n"
                    f"使用 `/check` 进行检定，发送剧情关键词推进故事"
                )
    
    async def _show_help(self) -> Tuple[bool, Optional[str], bool]:
        """显示加载存档帮助"""
        help_text = """💾 **加载存档命令帮助**

**使用方法:**
`/load <存档ID>`

**参数说明:**
- 存档ID: 6位数字的存档标识符

**示例:**
`/load 123456`

**注意:**
- 需要先注册才能加载存档
- 只有存档创建者或管理员可以加载
- 使用 `/save list` 查看自己的存档列表"""
        await self.send_text(help_text)
        return True, "显示加载存档帮助", True

# === 加入剧本命令 ===
class JoinCommand(BaseCommand):
    """加入剧本命令"""
    
    command_name = "join"
    command_description = "加入跑团剧本"
    command_pattern = r"^/join\s+(?P<session_id>\d{6})(?:\s+help)?$"
    intercept_message = True
    
    async def execute(self) -> Tuple[bool, Optional[str], bool]:
        try:
            session_id = self.matched_groups.get("session_id")
            
            # 处理help参数
            if session_id == "help":
                return await self._show_help()
                
            user_id = self.message.message_info.user_info.user_id
            
            # 检查用户注册
            registered, msg = check_user_registered(user_id)
            if not registered:
                await self.send_text(msg)
                return False, "用户未注册", True
            
            if session_id not in active_sessions:
                await self.send_text("❌ 剧本ID不存在或已过期")
                return False, "剧本不存在", True
                
            session = active_sessions[session_id]
            
            if session["status"] != "recruiting":
                await self.send_text("❌ 剧本已开始招募，无法加入")
                return False, "招募已结束", True
                
            if len(session["players"]) >= session["max_players"]:
                await self.send_text("❌ 玩家席位已满")
                return False, "席位已满", True
                
            # 检查是否已加入
            for player in session["players"]:
                if player["qq"] == user_id:
                    await self.send_text("❌ 您已经加入了这个剧本")
                    return False, "已加入", True
                
            # 添加玩家
            player_data = {
                "qq": user_id,
                "uid": user_registry[str(user_id)],
                "joined_time": datetime.now().isoformat(),
                "character_rid": None,
                "ready": False,
                "status": "alive"
            }
            session["players"].append(player_data)
            session["last_activity"] = datetime.now().isoformat()
            
            await self.send_text(
                f"✅ 玩家 {user_id} 成功加入剧本 {session['plot_name']}！\n"
                f"当前玩家: {len(session['players'])}/{session['max_players']}"
            )
            
            return True, "加入剧本成功", True
            
        except Exception as e:
            await self.send_text(f"❌ 加入剧本失败: {str(e)}")
            return False, f"加入失败: {str(e)}", True
    
    async def _show_help(self) -> Tuple[bool, Optional[str], bool]:
        """显示加入剧本帮助"""
        help_text = """🎭 **加入剧本命令帮助**

**使用方法:**
`/join <剧本ID>`

**参数说明:**
- 剧本ID: 6位数字的剧本标识符

**示例:**
`/join 123456`

**注意:**
- 需要先注册才能加入剧本
- 只能在剧本招募阶段加入
- 使用 `/trpg` 查看如何获取剧本ID"""
        await self.send_text(help_text)
        return True, "显示加入剧本帮助", True

# === 存档命令 ===
class SaveCommand(BaseCommand):
    """存档命令"""
    
    command_name = "save"
    command_description = "保存游戏进度"
    command_pattern = r"^/save(?:\s+(?P<action>\w+))?(?:\s+(?P<params>.+))?$"
    intercept_message = True
    
    async def execute(self) -> Tuple[bool, Optional[str], bool]:
        try:
            user_id = self.message.message_info.user_info.user_id
            
            action = self.matched_groups.get("action", "")
            params = self.matched_groups.get("params", "")
            
            # 处理help参数
            if action == "help":
                return await self._show_help()
                
            # 检查用户注册
            registered, msg = check_user_registered(user_id)
            if not registered:
                await self.send_text(msg)
                return False, "用户未注册", True
            
            if action == "list":
                return await self._list_saves(user_id)
            elif not action:  # 无参数时为保存
                return await self._save_game(user_id)
            else:
                await self.send_text("❌ 未知操作，使用 `/save help` 查看帮助")
                return False, "未知操作", True
                
        except Exception as e:
            await self.send_text(f"❌ 存档操作失败: {str(e)}")
            return False, f"存档操作失败: {str(e)}", True
    
    async def _save_game(self, user_id: str) -> Tuple[bool, Optional[str], bool]:
        """保存游戏"""
        # 查找用户当前会话
        current_session = None
        for session in active_sessions.values():
            if any(player["qq"] == user_id for player in session["players"]):
                current_session = session
                break
                
        if not current_session:
            await self.send_text("❌ 您没有在活跃的剧本中")
            return False, "无会话", True
            
        # 权限检查：只有团长或管理员可以保存
        if not is_session_creator(user_id, current_session["session_id"]) and not is_admin(user_id, self.plugin):
            await self.send_text("❌ 只有团长或管理员可以保存游戏")
            return False, "权限不足", True
            
        # 生成存档ID
        save_id = generate_save_id()
        
        # 创建存档数据
        save_data = {
            "save_id": save_id,
            "session_id": current_session["session_id"],
            "plot_name": current_session["plot_name"],
            "plot_content": current_session.get("plot_content", ""),
            "mode": current_session["mode"],
            "max_players": current_session["max_players"],
            "players": current_session["players"],
            "npcs": current_session["npcs"],
            "items": current_session.get("items", []),
            "current_progress": current_session["current_progress"],
            "save_time": datetime.now().isoformat(),
            "creator": current_session["creator"],
            "creator_uid": current_session["creator_uid"],
            "status": "incomplete"
        }
        
        # 保存到数据库和文件
        save_db[save_id] = save_data
        save_save_data(save_data)
        
        await self.send_text(
            f"💾 **游戏已保存！**\n"
            f"📁 存档ID: {save_id}\n"
            f"📜 剧本: {current_session['plot_name']}\n"
            f"👥 玩家数: {len(current_session['players'])}\n"
            f"⏰ 时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"
            f"💡 使用 `/load {save_id}` 加载此存档继续游戏"
        )
        
        return True, "游戏保存成功", True
    
    async def _list_saves(self, user_id: str) -> Tuple[bool, Optional[str], bool]:
        """列出用户的存档"""
        user_uid = user_registry.get(str(user_id))
        if not user_uid:
            await self.send_text("❌ 您还没有注册")
            return False, "未注册", True
            
        user_saves = get_user_saves_list(user_uid)
        
        if not user_saves:
            await self.send_text("📁 您还没有任何存档")
            return True, "无存档", True
            
        save_list = "📁 **您的存档列表**\n\n"
        
        for save in user_saves:
            save_time = datetime.fromisoformat(save['save_time']).strftime('%m-%d %H:%M')
            save_list += (
                f"🆔 **{save['save_id']}**\n"
                f"📖 {save['plot_name']} ({save['mode'].upper()})\n"
                f"👥 {save['player_count']}人 · ⏰ {save_time}\n\n"
            )
        
        save_list += "💡 使用 `/load 存档ID` 加载存档继续游戏"
        
        await self.send_text(save_list)
        return True, "显示存档列表", True
    
    async def _show_help(self) -> Tuple[bool, Optional[str], bool]:
        """显示存档帮助"""
        help_text = """💾 **存档命令帮助**

**保存游戏:**
`/save` - 保存当前游戏进度

**查看存档列表:**
`/save list` - 查看我的所有存档

**加载存档:**
`/load <存档ID>` - 加载存档继续游戏

**注意:**
- 保存游戏需要团长或管理员权限
- 需要在剧本中使用
- 存档ID为6位数字，使用 `/save list` 查看"""
        await self.send_text(help_text)
        return True, "显示存档帮助", True

# === 注册命令 ===
class RegisterCommand(BaseCommand):
    """用户注册命令"""
    
    command_name = "register"
    command_description = "用户注册"
    command_pattern = r"^/register(?:\s+help)?$"
    intercept_message = True
    
    async def execute(self) -> Tuple[bool, Optional[str], bool]:
        try:
            # 检查是否为私聊
            if hasattr(self.message, 'message_info') and hasattr(self.message.message_info, 'group_id'):
                await self.send_text("❌ 请私聊机器人进行注册以保护隐私")
                return False, "群聊注册被拒绝", True
                
            user_id = self.message.message_info.user_info.user_id
            
            if str(user_id) in user_registry:
                await self.send_text(f"✅ 您已注册，UID: {user_registry[str(user_id)]}")
                return True, "用户已注册", True
                
            # 生成新UID
            uid = generate_uid()
            user_registry[str(user_id)] = uid
            save_user_registry()
            
            await self.send_text(
                f"🎉 注册成功！\n"
                f"📝 QQ: {user_id}\n"
                f"🆔 UID: {uid}\n\n"
                f"此UID将用于所有跑团活动，请妥善保管"
            )
            
            return True, "注册成功", True
            
        except Exception as e:
            await self.send_text(f"❌ 注册失败: {str(e)}")
            return False, f"注册失败: {str(e)}", True

# === 状态查询命令 ===
class StatusCommand(BaseCommand):
    """状态查询命令"""
    
    command_name = "status"
    command_description = "查看当前角色状态"
    command_pattern = r"^/status(?:\s+help)?$"
    intercept_message = True
    
    async def execute(self) -> Tuple[bool, Optional[str], bool]:
        try:
            user_id = self.message.message_info.user_info.user_id
            
            # 处理help参数
            if hasattr(self, 'matched_groups') and self.matched_groups and self.matched_groups.get(0) == "help":
                return await self._show_help()
                
            # 检查用户注册
            registered, msg = check_user_registered(user_id)
            if not registered:
                await self.send_text(msg)
                return False, "用户未注册", True
                
            # 查找用户当前角色
            current_session, character = await self._get_user_character(user_id)
            if not character:
                await self.send_text("❌ 您没有在活跃的剧本中或有角色")
                return False, "无角色", True
                
            mode = character["mode"]
            attr_display = "\n".join([f"  {RULES[mode]['attribute_names'].get(attr, attr)}: {value}" 
                                    for attr, value in character['attributes'].items()])
            
            # 显示物品
            items_text = "无"
            if character.get("items"):
                items_text = "\n".join([f"  - {item['name']} x{item['quantity']}" for item in character["items"]])
            
            status_text = (
                f"🎭 **角色状态详情**\n\n"
                f"📝 名称: {character['name']}\n"
                f"🏷️ 职业: {character.get('profession', '无')}\n"
                f"🆔 RID: {character['rid']}\n"
                f"🎮 模式: {mode.upper()}\n"
                f"❤️ HP: {character['hp']}\n"
                f"🔮 MP: {character.get('mp', 0)}\n"
                f"📅 创建时间: {character['created_time'][:10]}\n\n"
                f"📊 **属性详情:**\n{attr_display}\n\n"
                f"📦 **物品:**\n{items_text}"
            )
            
            await self.send_text(status_text)
            return True, "显示角色状态", True
            
        except Exception as e:
            await self.send_text(f"❌ 查询状态失败: {str(e)}")
            return False, f"状态查询失败: {str(e)}", True
    
    async def _get_user_character(self, user_id: str) -> Tuple[Optional[Dict], Optional[Dict]]:
        """获取用户当前角色"""
        for session in active_sessions.values():
            for player in session["players"]:
                if player["qq"] == user_id and player["character_rid"]:
                    return session, character_db[player["character_rid"]]
        return None, None
    
    async def _show_help(self) -> Tuple[bool, Optional[str], bool]:
        """显示状态帮助"""
        help_text = """📊 **状态命令帮助**

**使用方法:**
`/status` - 查看当前角色完整状态

**显示内容:**
- 角色基本信息
- 所有属性值
- 当前HP/MP
- 拥有的物品

**注意:**
- 需要在剧本中使用
- 需要有角色才能查看"""
        await self.send_text(help_text)
        return True, "显示状态帮助", True

# === 剧本列表命令 ===
class PlotListCommand(BaseCommand):
    """剧本列表命令"""
    
    command_name = "plot_list"
    command_description = "查看可用剧本列表"
    command_pattern = r"^/plot\s+list(?:\s+help)?$"
    intercept_message = True
    
    async def execute(self) -> Tuple[bool, Optional[str], bool]:
        try:
            # 处理help参数
            if hasattr(self, 'matched_groups') and self.matched_groups and self.matched_groups.get(0) == "help":
                return await self._show_help()
                
            available_plots = get_available_plots()
            
            if not available_plots:
                await self.send_text(
                    f"📚 **可用剧本列表**\n\n"
                    f"暂无剧本文件\n\n"
                    f"💡 请将.txt剧本文件放入目录: {PLOTS_DIR}"
                )
                return True, "无剧本文件", True
            
            plot_list = "📚 **可用剧本列表**\n\n"
            for plot in available_plots:
                plot_list += f"• {plot}\n"
            
            plot_list += f"\n💡 使用 `/start <模式> plot=剧本名` 开始游戏"
            
            await self.send_text(plot_list)
            return True, "显示剧本列表", True
            
        except Exception as e:
            await self.send_text(f"❌ 获取剧本列表失败: {str(e)}")
            return False, f"获取剧本列表失败: {str(e)}", True
    
    async def _show_help(self) -> Tuple[bool, Optional[str], bool]:
        """显示剧本列表帮助"""
        help_text = """📚 **剧本列表命令帮助**

**使用方法:**
`/plot list` - 查看所有可用剧本

**注意:**
- 剧本文件需为.txt格式
- 将剧本文件放入plugins/TRPG_Plugin/plots/目录
- 使用剧本文件名（不含路径）开始游戏"""
        await self.send_text(help_text)
        return True, "显示剧本列表帮助", True

# === 跳过准备阶段命令 ===
class SkipPrepareCommand(BaseCommand):
    """跳过准备阶段命令"""
    
    command_name = "skip_prepare"
    command_description = "跳过准备阶段"
    command_pattern = r"^/skip\s+prepare(?:\s+help)?$"
    intercept_message = True
    
    async def execute(self) -> Tuple[bool, Optional[str], bool]:
        try:
            user_id = self.message.message_info.user_info.user_id
            
            # 处理help参数
            if hasattr(self, 'matched_groups') and self.matched_groups and self.matched_groups.get(0) == "help":
                return await self._show_help()
                
            # 检查用户注册
            registered, msg = check_user_registered(user_id)
            if not registered:
                await self.send_text(msg)
                return False, "用户未注册", True
                
            # 查找用户当前会话
            current_session = None
            for session in active_sessions.values():
                if any(player["qq"] == user_id for player in session["players"]):
                    current_session = session
                    break
                    
            if not current_session:
                await self.send_text("❌ 您没有在活跃的剧本中")
                return False, "无会话", True
                
            # 权限检查：只有团长或管理员可以跳过
            if not is_session_creator(user_id, current_session["session_id"]) and not is_admin(user_id, self.plugin):
                await self.send_text("❌ 只有团长或管理员可以跳过准备阶段")
                return False, "权限不足", True
                
            if current_session["status"] != "preparing":
                await self.send_text("❌ 当前不在准备阶段")
                return False, "不在准备阶段", True
            
            # 为没有角色的玩家生成随机角色
            for player in current_session["players"]:
                if not player.get("character_rid"):
                    random_char = generate_random_character(current_session["mode"], f"玩家{player['qq']}")
                    player["character_rid"] = random_char["rid"]
                    player["ready"] = True
                    
                    mode = current_session["mode"]
                    attr_display = "\n".join([f"  {RULES[mode]['attribute_names'].get(attr, attr)}: {value}" 
                                            for attr, value in random_char['attributes'].items()])
                    
                    await self.send_text(
                        f"🎲 **为玩家 {player['qq']} 生成了随机角色**\n"
                        f"🎭 名称: {random_char['name']}\n"
                        f"🏷️ 职业: {random_char['profession']}\n"
                        f"🆔 RID: {random_char['rid']}\n"
                        f"📊 属性详情:\n{attr_display}"
                    )
            
            current_session["status"] = "playing"
            await self.send_text(
                f"⏩ **准备阶段已跳过！**\n"
                f"游戏正式开始！\n\n"
                f"使用 `/check` 进行检定，发送剧情关键词推进故事"
            )
            
            return True, "跳过准备阶段成功", True
            
        except Exception as e:
            await self.send_text(f"❌ 跳过准备阶段失败: {str(e)}")
            return False, f"跳过失败: {str(e)}", True
    
    async def _show_help(self) -> Tuple[bool, Optional[str], bool]:
        """显示跳过准备阶段帮助"""
        help_text = """⏩ **跳过准备阶段命令帮助**

**使用方法:**
`/skip prepare` - 强制结束准备阶段，开始游戏

**注意:**
- 需要团长或管理员权限
- 未准备角色的玩家将被分配随机角色
- 只能在准备阶段使用"""
        await self.send_text(help_text)
        return True, "显示跳过准备阶段帮助", True

# === 踢出玩家命令 ===
class KickCommand(BaseCommand):
    """踢出玩家命令"""
    
    command_name = "kick"
    command_description = "踢出玩家"
    command_pattern = r"^/kick\s+force\s+(?P<target_uid>\d+)(?:\s+(?P<option>dr|sr))?(?:\s+help)?$"
    intercept_message = True
    
    async def execute(self) -> Tuple[bool, Optional[str], bool]:
        try:
            user_id = self.message.message_info.user_info.user_id
            target_uid = self.matched_groups.get("target_uid")
            option = self.matched_groups.get("option", "sr")  # 默认保存角色
            
            # 处理help参数
            if target_uid == "help":
                return await self._show_help()
                
            # 检查用户注册
            registered, msg = check_user_registered(user_id)
            if not registered:
                await self.send_text(msg)
                return False, "用户未注册", True
                
            # 查找用户当前会话
            current_session = None
            for session in active_sessions.values():
                if any(player["qq"] == user_id for player in session["players"]):
                    current_session = session
                    break
                    
            if not current_session:
                await self.send_text("❌ 您没有在活跃的剧本中")
                return False, "无会话", True
                
            # 权限检查：只有团长或管理员可以踢人
            if not is_session_creator(user_id, current_session["session_id"]) and not is_admin(user_id, self.plugin):
                await self.send_text("❌ 只有团长或管理员可以踢出玩家")
                return False, "权限不足", True
            
            # 查找目标玩家
            target_player = None
            for player in current_session["players"]:
                if player["uid"] == target_uid:
                    target_player = player
                    break
            
            if not target_player:
                await self.send_text("❌ 未找到该UID的玩家")
                return False, "玩家不存在", True
                
            # 执行踢出操作
            target_qq = target_player["qq"]
            character_rid = target_player.get("character_rid")
            
            if option == "dr" and character_rid:  # 删除角色
                delete_character(character_rid)
                action_text = "并删除了其角色"
            else:  # 保存角色
                action_text = "其角色已保存"
            
            # 从会话中移除玩家
            current_session["players"] = [p for p in current_session["players"] if p["uid"] != target_uid]
            
            await self.send_text(
                f"🚪 **已踢出玩家**\n"
                f"👤 QQ: {target_qq}\n"
                f"🆔 UID: {target_uid}\n"
                f"📝 {action_text}"
            )
            
            return True, "踢出玩家成功", True
            
        except Exception as e:
            await self.send_text(f"❌ 踢出玩家失败: {str(e)}")
            return False, f"踢出失败: {str(e)}", True
    
    async def _show_help(self) -> Tuple[bool, Optional[str], bool]:
        """显示踢出玩家帮助"""
        help_text = """🚪 **踢出玩家命令帮助**

**使用方法:**
`/kick force <目标UID> [dr|sr]`

**参数说明:**
- 目标UID: 要踢出玩家的UID
- dr: 删除玩家的角色（慎用）
- sr: 保存玩家的角色（默认）

**示例:**
`/kick force 12345678` - 踢出玩家但保存角色
`/kick force 12345678 dr` - 踢出玩家并删除角色

**注意:**
- 需要团长或管理员权限
- 需要在剧本中使用
- 删除角色操作不可逆，请谨慎使用"""
        await self.send_text(help_text)
        return True, "显示踢出玩家帮助", True

# === 骰子命令 ===
class DiceCommand(BaseCommand):
    """骰子命令"""
    
    command_name = "dice"
    command_description = "掷骰子"
    command_pattern = r"^/dice\s+D(?P<sides>\d+)(?:\s+help)?$"
    intercept_message = True
    
    async def execute(self) -> Tuple[bool, Optional[str], bool]:
        try:
            user_id = self.message.message_info.user_info.user_id
            
            sides = self.matched_groups.get("sides", "")
            
            # 处理help参数
            if sides == "help" or not sides:
                return await self._show_help()
                
            sides = int(sides)
            
            # 检查用户注册（非help命令需要注册）
            registered, msg = check_user_registered(user_id)
            if not registered:
                await self.send_text(msg)
                return False, "用户未注册", True
            
            if sides < 2 or sides > 1000:
                await self.send_text("❌ 骰子面数必须在2-1000之间")
                return False, "面数无效", True
                
            result = random.randint(1, sides)
            
            await self.send_text(f"🎲 掷出了 D{sides}: **{result}**")
            return True, f"掷骰结果: {result}", True
            
        except Exception as e:
            await self.send_text(f"❌ 掷骰失败: {str(e)}")
            return False, f"掷骰失败: {str(e)}", True
    
    async def _show_help(self) -> Tuple[bool, Optional[str], bool]:
        """显示掷骰帮助"""
        help_text = """🎲 **掷骰命令帮助**

**使用方法:**
`/dice D<面数>`
示例: `/dice D20` - 掷一个20面骰子

**说明:**
- 面数范围: 2-1000
- 无需加入剧本即可使用"""
        await self.send_text(help_text)
        return True, "显示掷骰帮助", True

# === 战斗管理命令 ===
class CombatCommand(BaseCommand):
    """战斗管理命令"""
    
    command_name = "combat"
    command_description = "战斗管理"
    command_pattern = r"^/combat\s+(?P<action>\w+)(?:\s+(?P<target>\S+))?(?:\s+help)?$"
    intercept_message = True
    
    async def execute(self) -> Tuple[bool, Optional[str], bool]:
        try:
            user_id = self.message.message_info.user_info.user_id
            
            action = self.matched_groups.get("action", "")
            
            # 处理help参数
            if action == "help":
                return await self._show_help()
                
            # 检查用户注册（非help命令需要注册）
            registered, msg = check_user_registered(user_id)
            if not registered:
                await self.send_text(msg)
                return False, "用户未注册", True
                
            target = self.matched_groups.get("target", "")
            
            # 查找用户当前会话
            current_session = None
            for session in active_sessions.values():
                if any(player["qq"] == user_id for player in session["players"]):
                    current_session = session
                    break
                    
            if not current_session:
                await self.send_text("❌ 您没有在活跃的剧本中")
                return False, "无会话", True
                
            session_id = current_session["session_id"]
            
            if action == "start":
                return await self._start_combat(session_id, user_id)
            elif action == "end":
                return await self._end_combat(session_id, user_id)
            elif action == "status":
                return await self._combat_status(session_id)
            elif action == "attack":
                return await self._attack(session_id, user_id, target)
            else:
                await self.send_text("❌ 未知战斗命令")
                return False, "未知命令", True
                
        except Exception as e:
            await self.send_text(f"❌ 战斗命令失败: {str(e)}")
            return False, f"战斗命令失败: {str(e)}", True
    
    async def _start_combat(self, session_id: str, user_id: str) -> Tuple[bool, Optional[str], bool]:
        """开始战斗"""
        if not is_session_creator(user_id, session_id) and not is_admin(user_id, self.plugin):
            await self.send_text("❌ 只有团长或管理员可以开始战斗")
            return False, "权限不足", True
            
        if session_id in combat_sessions:
            await self.send_text("❌ 战斗已经开始了")
            return False, "战斗已开始", True
            
        session = active_sessions[session_id]
        
        # 初始化战斗
        combat_sessions[session_id] = {
            "round": 1,
            "turn_order": [],
            "current_turn": 0,
            "participants": [],
            "status": "active"
        }
        
        combat = combat_sessions[session_id]
        
        # 添加玩家到战斗
        for player in session["players"]:
            if player["character_rid"]:
                character = character_db[player["character_rid"]]
                combat["participants"].append({
                    "type": "player",
                    "qq": player["qq"],
                    "character": character,
                    "initiative": random.randint(1, 20) + character["attributes"].get("dex", character["attributes"].get("敏捷", 0)) // 10,
                    "hp": character["hp"],
                    "status": "active"
                })
        
        # 添加NPC到战斗（如果有）
        for npc in session["npcs"]:
            if npc.get("in_combat", False):
                combat["participants"].append({
                    "type": "npc",
                    "npc_id": npc["npc_id"],
                    "name": npc["name"],
                    "initiative": random.randint(1, 20) + npc["attributes"].get("dex", 0) // 10,
                    "hp": npc["hp"],
                    "status": "active"
                })
        
        # 排序先攻
        combat["participants"].sort(key=lambda x: x["initiative"], reverse=True)
        combat["turn_order"] = [p for p in combat["participants"]]
        
        await self.send_text(
            f"⚔️ **战斗开始！**\n"
            f"🔄 回合: 1\n"
            f"🎯 先攻顺序:\n" + 
            "\n".join([f"{i+1}. {p.get('character', {}).get('name', p.get('name', '未知'))} (先攻: {p['initiative']})" 
                      for i, p in enumerate(combat['turn_order'])])
        )
        
        return True, "战斗开始", True
    
    async def _end_combat(self, session_id: str, user_id: str) -> Tuple[bool, Optional[str], bool]:
        """结束战斗"""
        if not is_session_creator(user_id, session_id) and not is_admin(user_id, self.plugin):
            await self.send_text("❌ 只有团长或管理员可以结束战斗")
            return False, "权限不足", True
            
        if session_id not in combat_sessions:
            await self.send_text("❌ 没有进行中的战斗")
            return False, "无战斗", True
            
        del combat_sessions[session_id]
        await self.send_text("🕊️ **战斗结束！**")
        
        return True, "战斗结束", True
    
    async def _combat_status(self, session_id: str) -> Tuple[bool, Optional[str], bool]:
        """战斗状态"""
        if session_id not in combat_sessions:
            await self.send_text("❌ 没有进行中的战斗")
            return False, "无战斗", True
            
        combat = combat_sessions[session_id]
        current = combat["turn_order"][combat["current_turn"]]
        
        status_text = (
            f"⚔️ **战斗状态**\n"
            f"🔄 回合: {combat['round']}\n"
            f"🎯 当前行动: {current.get('character', {}).get('name', current.get('name', '未知'))}\n\n"
            f"**参与者状态:**\n"
        )
        
        for participant in combat["participants"]:
            name = participant.get('character', {}).get('name', participant.get('name', '未知'))
            hp = participant['hp']
            status = participant['status']
            status_text += f"- {name}: HP {hp} [{status}]\n"
        
        await self.send_text(status_text)
        return True, "显示战斗状态", True
    
    async def _attack(self, session_id: str, user_id: str, target: str) -> Tuple[bool, Optional[str], bool]:
        """攻击行动"""
        if session_id not in combat_sessions:
            await self.send_text("❌ 没有进行中的战斗")
            return False, "无战斗", True
            
        combat = combat_sessions[session_id]
        current = combat["turn_order"][combat["current_turn"]]
        
        # 检查是否是当前玩家的回合
        if current.get("qq") != user_id:
            await self.send_text("❌ 不是你的回合")
            return False, "回合错误", True
        
        # 简化攻击逻辑
        attack_roll = random.randint(1, 20)
        damage = random.randint(1, 8)
        
        await self.send_text(
            f"⚔️ **攻击行动**\n"
            f"🎯 目标: {target}\n"
            f"🎲 攻击检定: {attack_roll}\n"
            f"💥 伤害: {damage}"
        )
        
        # 进入下一回合
        combat["current_turn"] = (combat["current_turn"] + 1) % len(combat["turn_order"])
        if combat["current_turn"] == 0:
            combat["round"] += 1
            
        return True, "攻击完成", True
    
    async def _show_help(self) -> Tuple[bool, Optional[str], bool]:
        """显示战斗帮助"""
        help_text = """⚔️ **战斗命令帮助**

**开始战斗:**
`/combat start` - 开始战斗（仅团长）

**结束战斗:**
`/combat end` - 结束战斗（仅团长）

**查看战斗状态:**
`/combat status` - 显示当前战斗状态

**攻击行动:**
`/combat attack <目标>` - 攻击指定目标

**注意:**
- 需要在剧本中使用
- 部分命令需要团长权限"""
        await self.send_text(help_text)
        return True, "显示战斗帮助", True

# === NPC管理命令 ===
class NPCCommand(BaseCommand):
    """NPC管理命令"""
    
    command_name = "npc"
    command_description = "NPC管理"
    command_pattern = r"^/npc\s+(?P<action>\w+)(?:\s+(?P<params>.+))?(?:\s+help)?$"
    intercept_message = True
    
    async def execute(self) -> Tuple[bool, Optional[str], bool]:
        try:
            user_id = self.message.message_info.user_info.user_id
            
            action = self.matched_groups.get("action", "")
            
            # 处理help参数
            if action == "help":
                return await self._show_help()
                
            # 检查用户注册（非help命令需要注册）
            registered, msg = check_user_registered(user_id)
            if not registered:
                await self.send_text(msg)
                return False, "用户未注册", True
                
            params = self.matched_groups.get("params", "")
            
            # 查找用户当前会话
            current_session = None
            for session in active_sessions.values():
                if any(player["qq"] == user_id for player in session["players"]):
                    current_session = session
                    break
                    
            if not current_session:
                await self.send_text("❌ 您没有在活跃的剧本中")
                return False, "无会话", True
                
            if not is_session_creator(user_id, current_session["session_id"]) and not is_admin(user_id, self.plugin):
                await self.send_text("❌ 只有团长或管理员可以管理NPC")
                return False, "权限不足", True
                
            if action == "create":
                return await self._create_npc(current_session, params)
            elif action == "list":
                return await self._list_npcs(current_session)
            elif action == "remove":
                return await self._remove_npc(current_session, params)
            else:
                await self.send_text("❌ 未知NPC命令")
                return False, "未知命令", True
                
        except Exception as e:
            await self.send_text(f"❌ NPC管理失败: {str(e)}")
            return False, f"NPC管理失败: {str(e)}", True
    
    async def _create_npc(self, session: Dict, params: str) -> Tuple[bool, Optional[str], bool]:
        """创建NPC"""
        # 解析参数: 名称 类型 {属性}
        pattern = r'^(\S+)\s+(\S+)\s+\{([^}]+)\}$'
        match = re.match(pattern, params)
        
        if not match:
            await self.send_text("❌ 参数格式错误！使用: /npc create 名称 类型 {属性}")
            return False, "参数格式错误", True
            
        name = match.group(1)
        npc_type = match.group(2)
        attributes_str = match.group(3)
        
        # 解析属性
        attributes = {}
        for attr_pair in attributes_str.split(';'):
            if ':' in attr_pair:
                key, value = attr_pair.split(':', 1)
                attributes[key.strip()] = int(value.strip())
        
        npc_id = generate_npc_id()
        npc_data = {
            "npc_id": npc_id,
            "name": name,
            "type": npc_type,
            "attributes": attributes,
            "hp": attributes.get("hp", 50),
            "session_id": session["session_id"],
            "created_time": datetime.now().isoformat()
        }
        
        # 保存NPC
        npc_db[npc_id] = npc_data
        session["npcs"].append(npc_data)
        session["last_activity"] = datetime.now().isoformat()
        
        await self.send_text(
            f"✅ NPC创建成功！\n"
            f"🎭 名称: {name}\n"
            f"🏷️ 类型: {npc_type}\n"
            f"🆔 ID: {npc_id}\n"
            f"❤️ HP: {npc_data['hp']}"
        )
        
        return True, "NPC创建成功", True
    
    async def _list_npcs(self, session: Dict) -> Tuple[bool, Optional[str], bool]:
        """列出NPC"""
        if not session["npcs"]:
            await self.send_text("📝 当前没有NPC")
            return True, "无NPC", True
            
        npc_list = "📝 **当前NPC列表:**\n"
        for npc in session["npcs"]:
            npc_list += f"- {npc['name']} ({npc['type']}) - ID: {npc['npc_id']} - HP: {npc['hp']}\n"
        
        await self.send_text(npc_list)
        return True, "显示NPC列表", True
    
    async def _remove_npc(self, session: Dict, npc_id: str) -> Tuple[bool, Optional[str], bool]:
        """移除NPC"""
        for i, npc in enumerate(session["npcs"]):
            if npc["npc_id"] == npc_id:
                del session["npcs"][i]
                if npc_id in npc_db:
                    del npc_db[npc_id]
                await self.send_text(f"✅ 已移除NPC: {npc['name']}")
                return True, "NPC移除成功", True
                
        await self.send_text("❌ NPC不存在")
        return False, "NPC不存在", True
    
    async def _show_help(self) -> Tuple[bool, Optional[str], bool]:
        """显示NPC帮助"""
        help_text = """🎭 **NPC管理命令帮助**

**创建NPC:**
`/npc create <名称> <类型> {属性}`
示例: `/npc create 守卫 战士 {str:16;dex:14;hp:30}`

**列出NPC:**
`/npc list` - 显示当前所有NPC

**移除NPC:**
`/npc remove <NPC_ID>` - 移除指定NPC

**注意:**
- 需要团长或管理员权限
- 需要在剧本中使用"""
        await self.send_text(help_text)
        return True, "显示NPC帮助", True

# === 物品管理命令 ===
class ItemCommand(BaseCommand):
    """物品管理命令"""
    
    command_name = "item"
    command_description = "物品管理"
    command_pattern = r"^/item\s+(?P<action>\w+)(?:\s+(?P<params>.+))?(?:\s+help)?$"
    intercept_message = True
    
    async def execute(self) -> Tuple[bool, Optional[str], bool]:
        try:
            user_id = self.message.message_info.user_info.user_id
            
            action = self.matched_groups.get("action", "")
            
            # 处理help参数
            if action == "help":
                return await self._show_help()
                
            # 检查用户注册（非help命令需要注册）
            registered, msg = check_user_registered(user_id)
            if not registered:
                await self.send_text(msg)
                return False, "用户未注册", True
                
            params = self.matched_groups.get("params", "")
            
            if action == "give":
                return await self._give_item(user_id, params)
            elif action == "list":
                return await self._list_items(user_id)
            else:
                await self.send_text("❌ 未知物品命令")
                return False, "未知命令", True
                
        except Exception as e:
            await self.send_text(f"❌ 物品管理失败: {str(e)}")
            return False, f"物品管理失败: {str(e)}", True
    
    async def _give_item(self, user_id: str, params: str) -> Tuple[bool, Optional[str], bool]:
        """给予物品"""
        # 解析参数: 玩家 物品名 数量
        parts = params.split()
        if len(parts) < 2:
            await self.send_text("❌ 参数错误！使用: /item give 玩家QQ 物品名 数量")
            return False, "参数错误", True
            
        target_qq = parts[0]
        item_name = parts[1]
        quantity = int(parts[2]) if len(parts) > 2 else 1
        
        # 查找目标玩家会话和角色
        target_session, target_character = await self._get_user_character(target_qq)
        if not target_session or not target_character:
            await self.send_text("❌ 目标玩家没有在活跃的剧本中或有角色")
            return False, "目标无效", True
            
        # 权限检查
        if not is_session_creator(user_id, target_session["session_id"]) and not is_admin(user_id, self.plugin):
            await self.send_text("❌ 只有团长或管理员可以分配物品")
            return False, "权限不足", True
        
        # 简化物品给予
        if "items" not in target_character:
            target_character["items"] = []
            
        target_character["items"].append({
            "name": item_name,
            "quantity": quantity,
            "obtained_time": datetime.now().isoformat()
        })
        
        save_character(target_character)
        
        await self.send_text(
            f"✅ 物品分配成功！\n"
            f"🎁 物品: {item_name} x{quantity}\n"
            f"👤 给予: {target_qq}\n"
            f"🎭 角色: {target_character['name']}"
        )
        
        return True, "物品给予成功", True
    
    async def _list_items(self, user_id: str) -> Tuple[bool, Optional[str], bool]:
        """列出物品"""
        current_session, character = await self._get_user_character(user_id)
        if not character:
            await self.send_text("❌ 您没有角色")
            return False, "无角色", True
            
        items = character.get("items", [])
        if not items:
            await self.send_text("📦 您的背包是空的")
            return True, "无物品", True
            
        item_list = "📦 **您的物品:**\n"
        for item in items:
            item_list += f"- {item['name']} x{item['quantity']}\n"
        
        await self.send_text(item_list)
        return True, "显示物品列表", True
    
    async def _get_user_character(self, user_id: str) -> Tuple[Optional[Dict], Optional[Dict]]:
        """获取用户角色"""
        for session in active_sessions.values():
            for player in session["players"]:
                if str(player["qq"]) == str(user_id) and player["character_rid"]:
                    return session, character_db[player["character_rid"]]
        return None, None
    
    async def _show_help(self) -> Tuple[bool, Optional[str], bool]:
        """显示物品帮助"""
        help_text = """📦 **物品管理命令帮助**

**给予物品:**
`/item give <玩家QQ> <物品名> [数量]`
示例: `/item give 123456 治疗药水 3`

**查看物品:**
`/item list` - 查看自己角色的物品

**注意:**
- 给予物品需要团长或管理员权限
- 需要在剧本中使用"""
        await self.send_text(help_text)
        return True, "显示物品帮助", True

# === 剧情推进器（修改为短篇幅）===
class PlotAdvancer(BaseAction):
    """剧情推进器 - 短篇幅版本"""
    
    action_name = "plot_advancer"
    action_description = "根据当前剧情条件推进故事发展"
    
    focus_activation_type = ActionActivationType.LLM_JUDGE
    normal_activation_type = ActionActivationType.KEYWORD
    activation_keywords = ["推进剧情", "继续故事", "下一步", "继续"]
    
    mode_enable = ChatMode.ALL
    parallel_action = False
    
    action_parameters = {
        "trigger_type": "剧情触发类型：auto-自动推进，manual-手动推进",
        "current_situation": "当前剧情状况描述"
    }
    
    action_require = [
        "当剧情需要推进时使用",
        "当玩家完成某个关键行动时使用", 
        "当团长要求推进剧情时使用",
        "当剧情陷入停滞时使用"
    ]
    
    async def execute(self) -> Tuple[bool, str]:
        try:
            # 获取当前会话
            stream_id = getattr(self.chat_stream, 'stream_id', 'unknown')
            current_session = None
            
            for session in active_sessions.values():
                if session.get('stream_id') == stream_id:
                    current_session = session
                    break
                    
            if not current_session:
                return False, "未找到当前游戏会话"
                
            # 调用AI模型推进剧情（短篇幅）
            plot_response = await self._advance_plot(current_session)
            if plot_response:
                # 限制在85字左右
                if len(plot_response) > 100:
                    plot_response = plot_response[:97] + "..."
                    
                await self.send_text(f"📖 {plot_response}")
                current_session['last_activity'] = datetime.now().isoformat()
                return True, "剧情推进成功"
            else:
                return False, "剧情推进失败"
                
        except Exception as e:
            return False, f"剧情推进错误: {str(e)}"
    
    async def _advance_plot(self, session: Dict) -> Optional[str]:
        """使用AI模型推进剧情 - 短篇幅版本"""
        api_url = self.get_config("llm.api_url")
        api_key = self.get_config("llm.api_key")
        model = self.get_config("llm.plot_model")
        temperature = self.get_config("llm.temperature")
        
        prompt = f"""
你是一位专业的{session['mode'].upper()}跑团主持人。请根据以下信息简短推进剧情（限85字内）：

当前剧本：{session['plot_name']}
当前进度：{session['current_progress']}
游戏模式：{session['mode'].upper()}

请生成下一阶段的简短剧情发展，保持原剧本风格。
回复请使用中文，控制在85字以内，保持简洁生动。
"""
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}"
        }
        
        payload = {
            "model": model,
            "messages": [
                {"role": "system", "content": "你是一位专业的TRPG游戏主持人，回复简短精炼"},
                {"role": "user", "content": prompt}
            ],
            "temperature": temperature,
            "max_tokens": 150  # 限制输出长度
        }
        
        try:
            async with aiohttp.ClientSession() as http_session:
                async with http_session.post(api_url, headers=headers, json=payload) as response:
                    if response.status == 200:
                        data = await response.json()
                        content = data.get("choices", [{}])[0].get("message", {}).get("content", "").strip()
                        # 更新会话进度
                        session['current_progress'] = "推进剧情"
                        return content
        except Exception as e:
            print(f"AI API调用失败: {e}")
            
        return "故事继续发展，前方等待你们的是新的挑战..."

# === 插件主类 ===
@register_plugin
class TRPGPlugin(BasePlugin):
    """TRPG跑团插件 - 支持CoC和DnD规则"""
    
    plugin_name = "TRPG-Master-Plugin"
    plugin_description = "支持CoC和DnD规则的跑团插件，包含完整的角色创建、检定、战斗和剧本系统"
    plugin_version = "1.0.0"
    plugin_author = "KArabella"
    enable_plugin = True
    
    dependencies = []
    python_dependencies = ["aiofiles", "aiohttp", "toml"]
    
    config_file_name = "config.toml"
    config_section_descriptions = {
        "plugin": "插件基础配置",
        "llm": "AI模型配置",
        "game": "游戏规则配置",
        "combat": "战斗系统配置",
        "admin": "管理员配置"
    }
    
    config_schema = {
        "plugin": {
            "enabled": ConfigField(type=bool, default=True, description="启用插件"),
            "auto_clean_days": ConfigField(type=int, default=10, description="自动清理存档天数")
        },
        "llm": {
            "plot_model": ConfigField(type=str, default="Qwen/Qwen2.5-14B-Instruct", description="剧情推进模型"),
            "api_url": ConfigField(type=str, default="https://api.siliconflow.cn/v1/chat/completions", description="模型API地址"),
            "api_key": ConfigField(type=str, default="", description="API密钥"),
            "temperature": ConfigField(type=float, default=0.8, description="生成随机性")
        },
        "game": {
            "default_mode": ConfigField(type=str, default="coc", description="默认规则模式"),
            "max_players": ConfigField(type=int, default=6, description="最大玩家数")
        },
        "combat": {
            "round_timeout": ConfigField(type=int, default=120, description="回合超时时间(秒)"),
            "enable_auto_initiative": ConfigField(type=bool, default=True, description="启用自动先攻")
        },
        "admin": {
            "admin_users": ConfigField(type=list, default=[], description="管理员QQ号列表")
        }
    }
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        print(f"🔧 TRPG插件初始化中...")
        self._ensure_config_exists()
        # 加载所有数据
        load_user_registry()
        load_character_db()
        load_save_db()
        print(f"✅ TRPG插件初始化完成")
    
    def _ensure_config_exists(self):
        """确保配置文件存在，如果不存在则创建默认配置"""
        config_path = PLUGIN_DIR / self.config_file_name
        
        if not config_path.exists():
            print(f"📁 正在创建默认配置文件: {config_path}")
            self._create_default_config(config_path)
        else:
            print(f"✅ 配置文件已存在: {config_path}")
    
    def _create_default_config(self, config_path: Path):
        """创建默认配置文件"""
        default_config = {
            "plugin": {
                "enabled": True,
                "auto_clean_days": 10
            },
            "llm": {
                "plot_model": "Qwen/Qwen2.5-14B-Instruct",
                "api_url": "https://api.siliconflow.cn/v1/chat/completions", 
                "api_key": "",
                "temperature": 0.8
            },
            "game": {
                "default_mode": "coc",
                "max_players": 6
            },
            "combat": {
                "round_timeout": 120,
                "enable_auto_initiative": True
            },
            "admin": {
                "admin_users": []
            }
        }
        
        try:
            config_content = f"""# TRPG跑团插件配置文件
# 配置版本: {self.plugin_version}
# 生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}

[plugin]
enabled = {str(default_config["plugin"]["enabled"]).lower()}
auto_clean_days = {default_config["plugin"]["auto_clean_days"]}

[llm]
plot_model = "{default_config["llm"]["plot_model"]}"
api_url = "{default_config["llm"]["api_url"]}"
api_key = "{default_config["llm"]["api_key"]}"
temperature = {default_config["llm"]["temperature"]}

[game]
default_mode = "{default_config["game"]["default_mode"]}"
max_players = {default_config["game"]["max_players"]}

[combat]
round_timeout = {default_config["combat"]["round_timeout"]}
enable_auto_initiative = {str(default_config["combat"]["enable_auto_initiative"]).lower()}

[admin]
admin_users = {default_config["admin"]["admin_users"]}
"""
            
            with open(config_path, 'w', encoding='utf-8') as f:
                f.write(config_content)
                
            print(f"✅ 默认配置文件创建成功: {config_path}")
            
        except Exception as e:
            print(f"❌ 创建配置文件失败: {e}")
            try:
                with open(config_path, 'w', encoding='utf-8') as f:
                    toml.dump(default_config, f)
                print(f"✅ 使用 TOML 格式创建配置文件成功: {config_path}")
            except Exception as e2:
                print(f"❌ TOML 格式创建也失败: {e2}")
    
    def get_plugin_components(self) -> List[Tuple[ComponentInfo, Type]]:
        """注册所有插件组件"""
        components = [
            (TRPGHelpCommand.get_command_info(), TRPGHelpCommand),
            (StartCommand.get_command_info(), StartCommand),
            (LoadCommand.get_command_info(), LoadCommand),
            (JoinCommand.get_command_info(), JoinCommand),
            (SaveCommand.get_command_info(), SaveCommand),
            (RegisterCommand.get_command_info(), RegisterCommand),
            (RoleCommand.get_command_info(), RoleCommand),
            (CheckCommand.get_command_info(), CheckCommand),
            (StatusCommand.get_command_info(), StatusCommand),
            (PlotListCommand.get_command_info(), PlotListCommand),
            (SkipPrepareCommand.get_command_info(), SkipPrepareCommand),
            (KickCommand.get_command_info(), KickCommand),
            (DiceCommand.get_command_info(), DiceCommand),
            (CombatCommand.get_command_info(), CombatCommand),
            (NPCCommand.get_command_info(), NPCCommand),
            (ItemCommand.get_command_info(), ItemCommand),
            (PlotAdvancer.get_action_info(), PlotAdvancer)
        ]
        print(f"📋 TRPG插件注册了 {len(components)} 个组件")
        return components

# 定时清理任务
async def cleanup_old_saves():
    """清理旧存档"""
    while True:
        await asyncio.sleep(24 * 60 * 60)  # 每天执行一次
        
        auto_clean_days = 10  # 默认10天
        cutoff_time = datetime.now() - timedelta(days=auto_clean_days)
        
        for save_file in SAVES_DIR.glob("*.json"):
            try:
                with open(save_file, 'r', encoding='utf-8') as f:
                    save_data = json.load(f)
                
                save_time = datetime.fromisoformat(save_data.get('save_time', '2000-01-01'))
                if save_time < cutoff_time:
                    save_file.unlink()
                    save_id = save_data.get('save_id')
                    if save_id in save_db:
                        del save_db[save_id]
                    print(f"已清理旧存档: {save_file.name}")
            except:
                continue

# 启动清理任务
asyncio.create_task(cleanup_old_saves())