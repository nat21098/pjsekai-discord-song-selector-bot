import discord
from discord import app_commands
import random
import os
import json
import traceback
import re
from typing import List, Set, Tuple, Optional
from dotenv import load_dotenv

load_dotenv()
JSON_PATH = 'songs.json'

# --- 認証設定 ---
# .env から許可されたサーバーIDとユーザーIDを読み込む
ALLOWED_GUILDS = [int(id.strip()) for id in os.getenv('ALLOWED_GUILDS', '').split(',') if id.strip()]
ALLOWED_USERS = [int(id.strip()) for id in os.getenv('ALLOWED_USERS', '').split(',') if id.strip()]

def is_authorized(guild_id: Optional[int], user_id: int) -> bool:
    """
    指定されたサーバーまたはユーザーが利用許可されているかチェックします。
    許可されたユーザー、または許可されたサーバーのメンバーであれば利用可能です。
    """
    # どちらの制限も設定されていない場合は、全員許可
    if not ALLOWED_USERS and not ALLOWED_GUILDS:
        return True

    # 1. ユーザー個別許可リストに載っている場合（DM等での利用を想定）
    if ALLOWED_USERS and user_id in ALLOWED_USERS:
        return True

    # 2. 許可されたサーバー内での実行である場合
    if ALLOWED_GUILDS and guild_id in ALLOWED_GUILDS:
        return True

    return False

DIFFICULTY_COLORS = {
    "EASY": 0x66dd11, "NORMAL": 0x33bbee, "HARD": 0xffaa00,
    "EXPERT": 0xee4466, "MASTER": 0xBB33EE, "APPEND": 0xff7dc9
}

# 略称マッピング
DIFF_MAP = {"e": "EASY", "n": "NORMAL", "h": "HARD", "x": "EXPERT", "m": "MASTER", "a": "APPEND"}
UNIT_MAP = {
    "vs": "VIRTUAL SINGER", "ln": "Leo/need", "mmj": "MORE MORE JUMP!", 
    "vbs": "Vivid BAD SQUAD", "ws": "ワンダーランズ×ショウタイム", 
    "25nc": "25時、ナイトコードで。", "oth": "その他"
}
UNIT_ALIAS_MAP = {
    "バチャシン": "VIRTUAL SINGER", "レオニ": "Leo/need", "モモジャン": "MORE MORE JUMP!",
    "ビビバス": "Vivid BAD SQUAD", "ワンダショ": "ワンダーランズ×ショウタイム",
    "ニーゴ": "25時、ナイトコードで。", "その他": "その他",
    "vs": "VIRTUAL SINGER", "ln": "Leo/need", "mmj": "MORE MORE JUMP!",
    "vbs": "Vivid BAD SQUAD", "ws": "ワンダーランズ×ショウタイム",
    "25nc": "25時、ナイトコードで。", "oth": "その他"
}

RANK_MATCH_RULES = {
    "beginner": {"levels": (18, 25), "append_levels": None},
    "bronze": {"levels": (23, 26), "append_levels": None},
    "silver": {"levels": (25, 28), "append_levels": None},
    "gold": {"levels": (26, 30), "append_levels": None},
    "platinum": {"levels": (28, 31), "append_levels": None},
    "diamond": {"levels": (29, 32), "append_levels": (27, 30)},
    "master": {"levels": (30, 37), "append_levels": (28, 50)}
}
RANK_ALIAS_MAP = {
    "ビギナー": "beginner", "ブロンズ": "bronze", "シルバー": "silver",
    "ゴールド": "gold", "プラチナ": "platinum", "ダイヤ": "diamond", "ダイヤモンド": "diamond", "マスター": "master",
    "beginner": "beginner", "bronze": "bronze", "silver": "silver",
    "gold": "gold", "platinum": "platinum", "diamond": "diamond", "master": "master",
    "beg": "beginner", "bro": "bronze", "sil": "silver", "gol": "gold", "pla": "platinum", "dia": "diamond", "mas": "master"
}

# 解析用正規表現
RE_UNITS = re.compile(r'(バチャシン|レオニ|モモジャン|ビビバス|ワンダショ|ニーゴ|その他|25nc|vs|ln|mmj|vbs|ws|oth)')
RE_DIFFS = re.compile(r'[enhxma]+')
RE_LEVEL = re.compile(r'(\d+-\d*|\d*-\d+|-\d+|\d+)')
RE_RANK = re.compile(r'(ビギナー|ブロンズ|シルバー|ゴールド|プラチナ|ダイヤモンド|ダイヤ|マスター|beginner|bronze|silver|gold|platinum|diamond|master|beg|bro|sil|gol|pla|dia|mas)')

# --- データベース読み込み ---
def load_db():
    if not os.path.exists(JSON_PATH):
        print(f"Error: {JSON_PATH} not found")
        return []
    try:
        with open(JSON_PATH, 'r', encoding='utf-8') as f:
            data = json.load(f)
        db = []
        for title, info in data.items():
            u = info.get("unit", "その他")
            for d, lv in info.items():
                if d in DIFFICULTY_COLORS and isinstance(lv, int):
                    db.append({"title": title, "diff": d, "lv": lv, "unit": u})
        print(f"[Success] {len(db)} 件の譜面データをロードしました")
        return db
    except Exception as e:
        print(f"Data load error: {e}")
        return []

songs_db = load_db()

# --- クエリ解析エンジン ---
class SongQuery:
    def __init__(self, raw_input: str):
        self.and_groups = [] # ANDで繋がった条件グループのリスト
        self._parse(raw_input)

    def _parse(self, text: str):
        clean_text = text.strip()
        if not clean_text.startswith('/') or len(clean_text) <= 1:
            raise ValueError("Invalid format")
        
        # 1. AND分割 (「/」 または 「スペース」)
        raw_query = clean_text[1:]
        and_text = raw_query.replace('/', '\uf001').replace(' ', '\uf001')
        and_parts = [p.strip() for p in and_text.split('\uf001') if p.strip()]
        
        if not and_parts:
            raise ValueError("Empty query")

        for part in and_parts:
            # 2. OR分割 (「,」)
            or_parts = [p.strip().lower() for p in part.split(',') if p.strip()]
            
            group_results = []
            for option in or_parts:
                # 3. NOT判定 (「!」)
                is_not = False
                if option.startswith('!'):
                    is_not = True
                    option = option[1:]
                
                if not option: continue
                
                # 4. 要素抽出
                # ランクマッチ
                found_rank_keys = RE_RANK.findall(option)
                rank_id = None
                if found_rank_keys:
                    r_str = found_rank_keys[0]
                    rank_id = RANK_ALIAS_MAP.get(r_str, r_str)
                rem = RE_RANK.sub('', option)

                # ユニット
                found_unit_keys = RE_UNITS.findall(rem)
                rem = RE_UNITS.sub('', rem)
                
                # 難易度
                found_diff_str = RE_DIFFS.findall(rem)
                diffs = set()
                for ds in found_diff_str:
                    if len(ds) > 1:
                        raise ValueError("難易度は複数繋げて指定できません")
                    for char in ds:
                        diffs.add(DIFF_MAP[char])
                if len(diffs) > 1:
                    raise ValueError("1つの条件内で難易度は1つしか指定できません")
                rem = RE_DIFFS.sub('', rem)
                
                # レベル
                found_lv_match = RE_LEVEL.search(rem)
                min_lv, max_lv, has_lv = 0, 50, False
                if found_lv_match:
                    has_lv = True
                    lv_str = found_lv_match.group()
                    if '-' in lv_str:
                        p = lv_str.split('-')
                        if p[0]: min_lv = int(p[0])
                        if p[1]: max_lv = int(p[1])
                    else:
                        min_lv = max_lv = int(lv_str)
                    rem = RE_LEVEL.sub('', rem)
                
                # 想定外の文字列が残っている場合は無効
                if rem.strip() or (not found_unit_keys and not diffs and not has_lv and not rank_id):
                    raise ValueError(f"Invalid segment: {option}")

                group_results.append({
                    "is_not": is_not,
                    "units": {UNIT_ALIAS_MAP[uk] for uk in found_unit_keys},
                    "diffs": diffs,
                    "min_lv": min_lv,
                    "max_lv": max_lv,
                    "has_lv": has_lv,
                    "rank": rank_id
                })
            
            if group_results:
                self.and_groups.append(group_results)

    def matches(self, song) -> bool:
        u, d, l = song['unit'], song['diff'], song['lv']
        
        # すべてのANDグループを満たす必要がある
        for or_group in self.and_groups:
            # いずれか一つのORオプションを満たせばOK
            group_satisfied = False
            for opt in or_group:
                m = True
                if opt['units'] and u not in opt['units']: m = False
                if opt['diffs'] and d not in opt['diffs']: m = False
                if opt['has_lv'] and not (opt['min_lv'] <= l <= opt['max_lv']): m = False
                
                if opt['rank']:
                    rule = RANK_MATCH_RULES[opt['rank']]
                    if d == 'APPEND':
                        if rule['append_levels'] is None:
                            m = False
                        elif not (rule['append_levels'][0] <= l <= rule['append_levels'][1]):
                            m = False
                    else:
                        if not (rule['levels'][0] <= l <= rule['levels'][1]):
                            m = False
                
                if opt['is_not']:
                    if not m: # マッチしないことが条件なのでOK
                        group_satisfied = True
                        break
                elif m: # マッチしたのでOK
                    group_satisfied = True
                    break
            
            if not group_satisfied: return False
        return True

# --- Persistence ---
SETTINGS_FILE = "ui_settings.json"

def load_user_settings(guild_id, user_id):
    if not os.path.exists(SETTINGS_FILE):
        return {}
    try:
        with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
            all_settings = json.load(f)
            key = f"DM_{user_id}" if guild_id == "DM" else str(guild_id)
            return all_settings.get(key, {})
    except Exception as e:
        print(f"Error loading settings: {e}")
        return {}

def save_user_settings(guild_id, user_id, settings):
    all_settings = {}
    if os.path.exists(SETTINGS_FILE):
        try:
            with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
                all_settings = json.load(f)
        except Exception:
            all_settings = {}
    
    key = f"DM_{user_id}" if guild_id == "DM" else str(guild_id)
    all_settings[key] = settings
    
    try:
        with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
            json.dump(all_settings, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"Error saving settings: {e}")

# --- UIs ---
def get_settings_text(rank_str, unit_str, diff_str, lv_str):
    return (
        "**【現在の設定】**\n"
        f"🏆 **ランク**　: {rank_str}\n"
        f"🎤 **ユニット**: {unit_str}\n"
        f"🎵 **難易度**: {diff_str}\n"
        f"🔢 **レベル**: {lv_str}"
    )

def get_ui_embed(rank_str="指定なし", unit_str="指定なし", diff_str="指定なし", lv_str="指定なし"):
    status_text = get_settings_text(rank_str, unit_str, diff_str, lv_str)
    embed = discord.Embed(
        title="🎮 プロセカ選曲アプリUI",
        description=f"下のメニューから条件を選んでから「🎲 ランダム選曲」を押してください。\n\n{status_text}",
        color=0x33bbee
    )
    return embed

class SongSelectorUI(discord.ui.View):
    def __init__(self, guild_id=None, user_id=None):
        super().__init__(timeout=None)
        self.guild_id = guild_id
        self.user_id = user_id
        
        saved = {}
        if guild_id and user_id:
            saved = load_user_settings(guild_id, user_id)
        
        self.selected_units = set(saved.get("units", []))
        self.selected_unit_labels = saved.get("unit_labels", [])
        self.selected_diffs = set(saved.get("diffs", []))
        self.selected_diff_labels = saved.get("diff_labels", [])
        self.selected_rank = saved.get("rank")
        self.selected_rank_label = saved.get("rank_label")
        self.selected_levels = set(saved.get("levels", []))
        self.selected_level_labels = saved.get("level_labels", [])

    async def update_embed(self, interaction: discord.Interaction):
        if self.guild_id and self.user_id:
            settings = {
                "units": list(self.selected_units),
                "unit_labels": self.selected_unit_labels,
                "diffs": list(self.selected_diffs),
                "diff_labels": self.selected_diff_labels,
                "rank": self.selected_rank,
                "rank_label": self.selected_rank_label,
                "levels": list(self.selected_levels),
                "level_labels": self.selected_level_labels
            }
            save_user_settings(self.guild_id, self.user_id, settings)
        
        rank_str = self.selected_rank_label if self.selected_rank_label else "指定なし"
        unit_str = ", ".join(self.selected_unit_labels) if self.selected_unit_labels else "指定なし"
        diff_str = ", ".join(self.selected_diff_labels) if self.selected_diff_labels else "指定なし"
        lv_str = ", ".join(self.selected_level_labels) if self.selected_level_labels else "指定なし"
        
        embed = get_ui_embed(rank_str, unit_str, diff_str, lv_str)
        await interaction.response.edit_message(embed=embed, view=self)
    
    @discord.ui.select(
        placeholder="ランクマッチ指定 (任意)",
        min_values=0,
        max_values=1,
        options=[
            discord.SelectOption(label="[ 指定なし ]", value="none", description="指定を解除します"),
            discord.SelectOption(label="ビギナー (Beginner)", value="beginner", description="Lv 18～25"),
            discord.SelectOption(label="ブロンズ (Bronze)", value="bronze", description="Lv 23～26"),
            discord.SelectOption(label="シルバー (Silver)", value="silver", description="Lv 25～28"),
            discord.SelectOption(label="ゴールド (Gold)", value="gold", description="Lv 26～30"),
            discord.SelectOption(label="プラチナ (Platinum)", value="platinum", description="Lv 28～31"),
            discord.SelectOption(label="ダイヤモンド (Diamond)", value="diamond", description="Lv 29～32, APPEND 27～30"),
            discord.SelectOption(label="マスター (Master)", value="master", description="Lv 30～, APPEND 28～")
        ],
        custom_id="select_rank"
    )
    async def select_rank(self, interaction: discord.Interaction, select: discord.ui.Select):
        val = select.values[0] if select.values else None
        if val == "none" or not val:
            self.selected_rank = None
            self.selected_rank_label = None
        else:
            self.selected_rank = val
            self.selected_rank_label = next((opt.label for opt in select.options if opt.value == val), None)
            self.selected_units = set()
            self.selected_unit_labels = []
            self.selected_diffs = set()
            self.selected_diff_labels = []
            self.selected_levels = set()
            self.selected_level_labels = []
        await self.update_embed(interaction)

    @discord.ui.select(
        placeholder="ユニットを選択 (複数可)",
        min_values=0,
        max_values=8,
        options=[
            discord.SelectOption(label="[ 指定なし ]", value="none", description="指定を解除します"),
            discord.SelectOption(label="VIRTUAL SINGER", value="VIRTUAL SINGER"),
            discord.SelectOption(label="Leo/need", value="Leo/need"),
            discord.SelectOption(label="MORE MORE JUMP!", value="MORE MORE JUMP!"),
            discord.SelectOption(label="Vivid BAD SQUAD", value="Vivid BAD SQUAD"),
            discord.SelectOption(label="ワンダーランズ×ショウタイム", value="ワンダーランズ×ショウタイム"),
            discord.SelectOption(label="25時、ナイトコードで。", value="25時、ナイトコードで。"),
            discord.SelectOption(label="その他", value="その他"),
        ],
        custom_id="select_unit"
    )
    async def select_unit(self, interaction: discord.Interaction, select: discord.ui.Select):
        if "none" in select.values:
            self.selected_units = set()
            self.selected_unit_labels = []
        else:
            self.selected_units = set(select.values)
            self.selected_unit_labels = [opt.label for opt in select.options if opt.value in select.values]
            self.selected_rank = None
            self.selected_rank_label = None
        await self.update_embed(interaction)

    @discord.ui.select(
        placeholder="難易度を選択 (複数可)",
        min_values=0,
        max_values=7,
        options=[
            discord.SelectOption(label="[ 指定なし ]", value="none", description="指定を解除します"),
            discord.SelectOption(label="EASY", value="EASY", description="緑"),
            discord.SelectOption(label="NORMAL", value="NORMAL", description="青"),
            discord.SelectOption(label="HARD", value="HARD", description="黄"),
            discord.SelectOption(label="EXPERT", value="EXPERT", description="赤"),
            discord.SelectOption(label="MASTER", value="MASTER", description="紫"),
            discord.SelectOption(label="APPEND", value="APPEND", description="桃"),
        ],
        custom_id="select_diff"
    )
    async def select_diff(self, interaction: discord.Interaction, select: discord.ui.Select):
        if "none" in select.values:
            self.selected_diffs = set()
            self.selected_diff_labels = []
        else:
            self.selected_diffs = set(select.values)
            self.selected_diff_labels = [opt.label for opt in select.options if opt.value in select.values]
            self.selected_rank = None
            self.selected_rank_label = None
        await self.update_embed(interaction)

    @discord.ui.select(
        placeholder="レベルを選択 (最大2つで範囲指定)",
        min_values=0,
        max_values=2,
        options=[
            discord.SelectOption(label="[ 指定なし ]", value="none", description="指定を解除します"),
            discord.SelectOption(label="〜 15", value="5-15"),
            discord.SelectOption(label="16", value="16"),
            discord.SelectOption(label="17", value="17"),
            discord.SelectOption(label="18", value="18"),
            discord.SelectOption(label="19", value="19"),
            discord.SelectOption(label="20", value="20"),
            discord.SelectOption(label="21", value="21"),
            discord.SelectOption(label="22", value="22"),
            discord.SelectOption(label="23", value="23"),
            discord.SelectOption(label="24", value="24"),
            discord.SelectOption(label="25", value="25"),
            discord.SelectOption(label="26", value="26"),
            discord.SelectOption(label="27", value="27"),
            discord.SelectOption(label="28", value="28"),
            discord.SelectOption(label="29", value="29"),
            discord.SelectOption(label="30", value="30"),
            discord.SelectOption(label="31", value="31"),
            discord.SelectOption(label="32", value="32"),
            discord.SelectOption(label="33", value="33"),
            discord.SelectOption(label="34", value="34"),
            discord.SelectOption(label="35", value="35"),
            discord.SelectOption(label="36", value="36"),
            discord.SelectOption(label="37", value="37"),
            discord.SelectOption(label="38", value="38")
        ],
        custom_id="select_level"
    )
    async def select_level(self, interaction: discord.Interaction, select: discord.ui.Select):
        if "none" in select.values:
            self.selected_levels = set()
            self.selected_level_labels = []
        else:
            self.selected_levels = set()
            all_nums = []
            for v in select.values:
                if '-' in v:
                    parts = v.split('-')
                    if parts[0]: all_nums.append(int(parts[0]))
                    if parts[1]: all_nums.append(int(parts[1]))
                else:
                    all_nums.append(int(v))
            
            real_min = min(all_nums) if all_nums else 5
            real_max = max(all_nums) if all_nums else 50
            self.selected_levels.update(range(real_min, real_max + 1))
            
            if real_min <= 5 and real_max >= 38: label_str = "全レベル"
            elif real_min <= 5: label_str = f"〜 {real_max}"
            elif real_min == real_max: label_str = f"{real_min}"
            else: label_str = f"{real_min} 〜 {real_max}"
                
            self.selected_level_labels = [label_str]
            self.selected_rank = None
            self.selected_rank_label = None
        await self.update_embed(interaction)

    @discord.ui.button(label="🎲 ランダム選曲", style=discord.ButtonStyle.primary, custom_id="btn_draw")
    async def btn_draw(self, interaction: discord.Interaction, button: discord.ui.Button):
        results = []
        for s in songs_db:
            m = True
            if self.selected_units and s['unit'] not in self.selected_units: m = False
            if self.selected_diffs and s['diff'] not in self.selected_diffs: m = False
            if self.selected_rank:
                rule = RANK_MATCH_RULES[self.selected_rank]
                if s['diff'] == 'APPEND':
                    if not rule['append_levels'] or not (rule['append_levels'][0] <= s['lv'] <= rule['append_levels'][1]): m = False
                elif not (rule['levels'][0] <= s['lv'] <= rule['levels'][1]): m = False
            if self.selected_levels and s['lv'] not in self.selected_levels: m = False
            if m: results.append(s)
        
        if not results:
            await interaction.response.send_message("❌ 条件に合う曲が見つかりませんでした。", ephemeral=True)
            return
            
        s = random.choice(results)
        embed = discord.Embed(title=s['title'], description=f"{s['diff']} Lv.{s['lv']}\n{s['unit']}", color=DIFFICULTY_COLORS.get(s['diff']))
        await interaction.response.send_message(embed=embed)

# --- Bot本体 ---
class MyClient(discord.Client):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.tree = app_commands.CommandTree(self)

    async def setup_hook(self):
        self.add_view(SongSelectorUI(None, None))
        await self.tree.sync()

intents = discord.Intents.default()
intents.message_content = True
bot = MyClient(intents=intents)

# -- コマンド登録 --
@bot.tree.command(name="app", description="アプリ（UI）モードでプロセカ選曲を開きます")
async def slash_app(interaction: discord.Interaction):
    if not is_authorized(interaction.guild_id, interaction.user.id):
        await interaction.response.send_message("❌ このBotを利用する権限がありません。", ephemeral=True)
        return
    guild_id = interaction.guild_id if interaction.guild_id else "DM"
    view = SongSelectorUI(guild_id, interaction.user.id)
    await interaction.response.send_message(embed=get_ui_embed(
        rank_str=view.selected_rank_label if view.selected_rank_label else "指定なし",
        unit_str=", ".join(view.selected_unit_labels) if view.selected_unit_labels else "指定なし",
        diff_str=", ".join(view.selected_diff_labels) if view.selected_diff_labels else "指定なし",
        lv_str=", ".join(view.selected_level_labels) if view.selected_level_labels else "指定なし"
    ), view=view)

@bot.tree.command(name="config", description="現在の選曲アプリの設定を確認します")
async def slash_config(interaction: discord.Interaction):
    if not is_authorized(interaction.guild_id, interaction.user.id):
        await interaction.response.send_message("❌ このBotを利用する権限がありません。", ephemeral=True)
        return
    guild_id = interaction.guild_id if interaction.guild_id else "DM"
    view = SongSelectorUI(guild_id, interaction.user.id)
    status_text = get_settings_text(
        view.selected_rank_label if view.selected_rank_label else "指定なし",
        ", ".join(view.selected_unit_labels) if view.selected_unit_labels else "指定なし",
        ", ".join(view.selected_diff_labels) if view.selected_diff_labels else "指定なし",
        ", ".join(view.selected_level_labels) if view.selected_level_labels else "指定なし"
    )
    embed = discord.Embed(title="⚙️ 現在の設定確認", description=f"保存されている設定は以下の通りです。`/app` で変更できます。\n\n{status_text}", color=0x33bbee)
    await interaction.response.send_message(embed=embed)

@bot.tree.command(name="random", description="条件テキストを指定して選曲します（例: ln,vbs m29-31）")
@app_commands.describe(query="選曲条件（例: ln,vbs m29-） 省略で全曲ランダム")
async def slash_random(interaction: discord.Interaction, query: str = ""):
    if not is_authorized(interaction.guild_id, interaction.user.id):
        await interaction.response.send_message("❌ このBotを利用する権限がありません。", ephemeral=True)
        return
    if not query or query.lower() == "all":
        if not songs_db:
            await interaction.response.send_message("❌ 楽曲データが見つかりません。")
            return
        s = random.choice(songs_db)
        embed = discord.Embed(title=s['title'], description=f"{s['diff']} Lv.{s['lv']}\n{s['unit']}", color=DIFFICULTY_COLORS.get(s['diff']))
        await interaction.response.send_message(embed=embed)
        return
    try:
        q = SongQuery("/" + query)
        results = [s for s in songs_db if q.matches(s)]
        if not results:
            await interaction.response.send_message("❌ 条件に合う曲が見つかりませんでした。")
            return
        s = random.choice(results)
        embed = discord.Embed(title=s['title'], description=f"{s['diff']} Lv.{s['lv']}\n{s['unit']}", color=DIFFICULTY_COLORS.get(s['diff']))
        await interaction.response.send_message(embed=embed)
    except Exception as e:
        await interaction.response.send_message(f"❌ 条件の解析に失敗しました: {e}", ephemeral=True)

@bot.tree.context_menu(name="選曲アプリを開く")
async def context_app(interaction: discord.Interaction, message: discord.Message):
    if not is_authorized(interaction.guild_id, interaction.user.id):
        await interaction.response.send_message("❌ このBotを利用する権限がありません。", ephemeral=True)
        return
    guild_id = interaction.guild_id if interaction.guild_id else "DM"
    view = SongSelectorUI(guild_id, interaction.user.id)
    await interaction.response.send_message(embed=get_ui_embed(
        rank_str=view.selected_rank_label if view.selected_rank_label else "指定なし",
        unit_str=", ".join(view.selected_unit_labels) if view.selected_unit_labels else "指定なし",
        diff_str=", ".join(view.selected_diff_labels) if view.selected_diff_labels else "指定なし",
        lv_str=", ".join(view.selected_level_labels) if view.selected_level_labels else "指定なし"
    ), view=view, ephemeral=True)

@bot.event
async def on_ready():
    print(f"✅ Bot Online: {bot.user}")
    if ALLOWED_GUILDS:
        for guild in bot.guilds:
            if guild.id not in ALLOWED_GUILDS:
                print(f"⚠️ 許可されていないサーバー({guild.name})を検知したため、退出します。")
                await guild.leave()

@bot.event
async def on_guild_join(guild):
    if ALLOWED_GUILDS and guild.id not in ALLOWED_GUILDS:
        print(f"⚠️ 許可されていないサーバー({guild.name})に追加されたため、退出しました。")
        await guild.leave()

@bot.event
async def on_message(message):
    if message.author.bot: return
    if not is_authorized(message.guild.id if message.guild else None, message.author.id):
        return

    if not bot.user.mentioned_in(message):
        return

    msg = message.content.strip()
    mention_str1 = f"<@{bot.user.id}>"
    mention_str2 = f"<@!{bot.user.id}>"
    
    if msg.startswith(mention_str1):
        msg = msg[len(mention_str1):].strip()
    elif msg.startswith(mention_str2):
        msg = msg[len(mention_str2):].strip()
    else:
        return

    if not msg.startswith('/'):
        return
        
    msg = msg[1:]

    parts = msg.split(None, 1)
    if not parts:
        return
    else:
        cmd = parts[0].lower()
        query = parts[1] if len(parts) > 1 else ""

    if cmd == 'help':
        embed = discord.Embed(
            title="📖 プロセカ選曲Bot 操作マニュアル", 
            color=0x33bbee, 
            description="本Botを使用する際は、メンション（`@プロセカ選曲Bot`）の後に `/コマンド` を入力してください。\n使用例: `@プロセカ選曲Bot /app`"
        )
        embed.add_field(
            name="🎮 基本コマンド一覧", 
            value="**`/app`** : GUIメニューを起動し、ボタン操作にて選曲条件の設定および選曲を行います。\n"
                  "**`/all`** : 登録済み全楽曲の中からランダムに1曲を抽選します。\n"
                  "**`/config`** : 現在保存されている選曲条件の設定内容を表示します。", 
            inline=False
        )
        embed.add_field(
            name="⌨️ テキストによる条件指定 (`/[条件]`)", 
            value="テキスト形式で選曲条件を直接指定することが可能です。\n"
                  "使用例: `@プロセカ選曲Bot /ln m 29-31`（レオニ / MASTER / Lv.29〜31）", 
            inline=False
        )
        embed.add_field(
            name="🎵 難易度の指定（アルファベット）", 
            value="`e`：EASY　`n`：NORMAL　`h`：HARD　`x`：EXPERT　`m`：MASTER　`a`：APPEND",
            inline=False
        )
        embed.add_field(
            name="🎤 ユニットの指定", 
            value="`vs`：バーチャル・シンガー　`ln`：Leo/need　`mmj`：MORE MORE JUMP!　`vbs`：Vivid BAD SQUAD　`ws`：ワンダーランズ×ショウタイム　`25nc`：25時、ナイトコードで。　`oth`：その他",
            inline=False
        )
        embed.add_field(
            name="🔢 レベルの指定（数字）", 
            value="`25`：Lv.25のみ　`25-28`：Lv.25〜28　`28-`：Lv.28以上　`-25`：Lv.25以下",
            inline=False
        )
        embed.add_field(
            name="🚫 除外指定および複合条件の指定", 
            value="条件の先頭に `-` を付加することで、該当条件を除外することができます。\n"
                  "（例: `-a`：APPEND以外　`-28-`：Lv.28以上を除外）\n"
                  "複数の条件を指定する場合は、**半角スペース**で区切って入力してください。\n"
                  "使用例: `ln -a`（レオニ かつ APPEND以外）", 
            inline=False
        )
        await message.reply(embed=embed, mention_author=False)
    elif cmd == 'app':
        guild_id = message.guild.id if message.guild else "DM"
        view = SongSelectorUI(guild_id, message.author.id)
        await message.reply(embed=get_ui_embed(
            view.selected_rank_label if view.selected_rank_label else "指定なし",
            ", ".join(view.selected_unit_labels) if view.selected_unit_labels else "指定なし",
            ", ".join(view.selected_diff_labels) if view.selected_diff_labels else "指定なし",
            ", ".join(view.selected_level_labels) if view.selected_level_labels else "指定なし"
        ), view=view, mention_author=False)
    elif cmd == 'config':
        guild_id = message.guild.id if message.guild else "DM"
        view = SongSelectorUI(guild_id, message.author.id)
        text = get_settings_text(
            view.selected_rank_label if view.selected_rank_label else "指定なし",
            ", ".join(view.selected_unit_labels) if view.selected_unit_labels else "指定なし",
            ", ".join(view.selected_diff_labels) if view.selected_diff_labels else "指定なし",
            ", ".join(view.selected_level_labels) if view.selected_level_labels else "指定なし"
        )
        embed = discord.Embed(title="⚙️ 現在の設定確認", description=text, color=0x33bbee)
        await message.reply(embed=embed, mention_author=False)
    elif cmd == 'all':
        s = random.choice(songs_db)
        embed = discord.Embed(title=s['title'], description=f"{s['diff']} Lv.{s['lv']}\n{s['unit']}", color=DIFFICULTY_COLORS.get(s['diff']))
        await message.reply(embed=embed, mention_author=False)
    else:
        try:
            q = SongQuery("/" + cmd + " " + query)
            res = [s for s in songs_db if q.matches(s)]
            if not res:
                await message.reply("❌ 条件に合う曲が見つかりませんでした。", mention_author=False)
            else:
                s = random.choice(res)
                embed = discord.Embed(title=s['title'], description=f"{s['diff']} Lv.{s['lv']}\n{s['unit']}", color=DIFFICULTY_COLORS.get(s['diff']))
                await message.reply(embed=embed, mention_author=False)
        except:
            pass

# --- 起動ブロック ---
if __name__ == "__main__":
    token = os.getenv('DISCORD_BOT_TOKEN')
    if not token:
        print("Error: DISCORD_BOT_TOKEN is not set.")
    else:
        bot.run(token)
