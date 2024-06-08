import discord
from discord import app_commands
from discord.ui import Button, View
import sqlite3
from datetime import datetime, timedelta
from tokenDiscord import TOKEN
from threading import Lock
import asyncio

MAX_TOTAL_BET_PER_USER = 500000
CANCELATION_WINDOW = timedelta(minutes=5)
team_closed = {}  # 팀 참가 마감 상태를 관리하는 변수
BASE_MMR = 1600  # 기본 MMR 값 골드4
MMR_CHANGE = 50

# Intents
intents = discord.Intents.default()
intents.message_content = True

# Initialize bot
class MyBot(discord.Client):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.tree = discord.app_commands.CommandTree(self)
        self.team_lock = asyncio.Lock()  # Lock 초기화

    async def setup_hook(self):
        await self.tree.sync()

bot = MyBot(intents=intents)

# Database lock
db_lock = Lock()

# Singleton database connection
def get_db_connection():
    conn = sqlite3.connect('points.db', timeout=30)
    return conn

# Database interaction functions
def initialize_database():
    conn = sqlite3.connect('points.db')
    cursor = conn.cursor()
    
    # Create users table
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS users (
        user_id TEXT PRIMARY KEY,
        points INTEGER DEFAULT 0
    )
    ''')

    # Create matches table
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS matches (
        match_id INTEGER PRIMARY KEY AUTOINCREMENT,
        match_name TEXT NOT NULL,
        team1 TEXT NOT NULL,
        team2 TEXT NOT NULL,
        date TIMESTAMP NOT NULL,
        result TEXT,
        team1_dividend REAL DEFAULT 1.0,
        team2_dividend REAL DEFAULT 1.0,
        closed INTEGER DEFAULT 0,
        team1_total_bet INTEGER DEFAULT 0,
        team2_total_bet INTEGER DEFAULT 0
    )
    ''')

    # Create bets table
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS bets (
        bet_id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id TEXT NOT NULL,
        match_id INTEGER NOT NULL,
        team TEXT NOT NULL,
        amount INTEGER NOT NULL,
        timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (match_id) REFERENCES matches(match_id)
    )
    ''')

    # Create teams table
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS teams (
        match_name TEXT,
        user_id TEXT,
        team INTEGER,
        PRIMARY KEY (match_name, user_id)
    )
    ''')

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS records (
            user_id TEXT PRIMARY KEY,
            wins INTEGER DEFAULT 0,
            losses INTEGER DEFAULT 0,
            mmr INTEGER DEFAULT 1600,
            streak INTEGER DEFAULT 0
        )
    ''')

    conn.commit()
    conn.close()

def add_match(match_name, team1, team2, date):
    with db_lock, get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute('''
        INSERT INTO matches (match_name, team1, team2, date, team1_dividend, team2_dividend)
        VALUES (?, ?, ?, ?, ?, ?)
        ''', (match_name, team1, team2, date, 1.0, 1.0))
        conn.commit()

def get_matches():
    with db_lock, get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute('SELECT * FROM matches WHERE result IS NULL')
        matches = cursor.fetchall()
        return matches

def place_bet(user_id, match_id, team, amount):
    if is_betting_closed(match_id):
        return False

    # Check total bets by this user on this match
    with db_lock, get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute('SELECT SUM(amount) FROM bets WHERE user_id = ? AND match_id = ?', (user_id, match_id))
        total_bet_by_user = cursor.fetchone()[0] or 0

    if total_bet_by_user + amount > MAX_TOTAL_BET_PER_USER:
        return False, None  # Total bet exceeds limit
    
    with db_lock, get_db_connection() as conn:
        cursor = conn.cursor()
        
        # Fetch the team names and check if the match exists
        cursor.execute('SELECT team1, team2 FROM matches WHERE match_id = ?', (match_id,))
        match = cursor.fetchone()
        if not match:
            return False
        
        team1, team2 = match
        
        # Insert the bet
        cursor.execute('''
        INSERT INTO bets (user_id, match_id, team, amount, timestamp)
        VALUES (?, ?, ?, ?, ?)
        ''', (user_id, match_id, team, amount, datetime.now().strftime('%Y-%m-%d %H:%M:%S')))

        # Get the inserted bet_id
        bet_id = cursor.lastrowid
        
        # Update total bet amounts
        if team == team1:
            cursor.execute('UPDATE matches SET team1_total_bet = team1_total_bet + ? WHERE match_id = ?', (amount, match_id))
        elif team == team2:
            cursor.execute('UPDATE matches SET team2_total_bet = team2_total_bet + ? WHERE match_id = ?', (amount, match_id))
        else:
            return False
        
        # Update dividends
        cursor.execute('SELECT team1_total_bet, team2_total_bet FROM matches WHERE match_id = ?', (match_id,))
        totals = cursor.fetchone()
        if not totals:
            return False

        team1_total_bet, team2_total_bet = totals
        total_bet = team1_total_bet + team2_total_bet

        if total_bet == 0:
            return False

        team1_dividend = total_bet / team1_total_bet if team1_total_bet > 0 else 1.0
        team2_dividend = total_bet / team2_total_bet if team2_total_bet > 0 else 1.0

        # 소숫점 둘째 자리 까지 반올림
        team1_dividend = round(team1_dividend, 2)
        team2_dividend = round(team2_dividend, 2)

        cursor.execute('UPDATE matches SET team1_dividend = ?, team2_dividend = ? WHERE match_id = ?',
                       (team1_dividend, team2_dividend, match_id))
        
        conn.commit()
        return True, bet_id

def get_user_points(user_id):
    with db_lock, get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute('SELECT points FROM users WHERE user_id = ?', (user_id,))
        result = cursor.fetchone()
        return result[0] if result else 0

def set_user_points(user_id, points):
    with db_lock, get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute('INSERT OR REPLACE INTO users (user_id, points) VALUES (?, ?)', (user_id, points))
        conn.commit()

def close_match(match_id, winning_team):
    with db_lock, get_db_connection() as conn:
        cursor = conn.cursor()
        
        # Update the match result
        cursor.execute('UPDATE matches SET result = ? WHERE match_id = ?', (winning_team, match_id,))
        
        # Get the match details
        cursor.execute('SELECT team1, team2, team1_dividend, team2_dividend FROM matches WHERE match_id = ?', (match_id,))
        match = cursor.fetchone()
        
        if not match:
            return
        
        team1, team2, team1_dividend, team2_dividend = match
        winning_dividend = team1_dividend if winning_team == team1 else team2_dividend
        
        # Get all bets on the match
        cursor.execute('SELECT user_id, team, amount FROM bets WHERE match_id = ?', (match_id,))
        bets = cursor.fetchall()
        
        # Fetch current points for all users with bets on the match
        user_points = {}
        for bet in bets:
            user_id, team, amount = bet
            if user_id not in user_points:
                cursor.execute('SELECT points FROM users WHERE user_id = ?', (user_id,))
                result = cursor.fetchone()
                user_points[user_id] = result[0] if result else 0
        
        # Calculate winnings and update points
        for bet in bets:
            user_id, team, amount = bet
            if team == winning_team:
                winnings = amount * winning_dividend * 0.95
                winnings = round(winnings)
                user_points[user_id] += winnings
        
        # Update user points in a single transaction
        for user_id, points in user_points.items():
            cursor.execute('INSERT OR REPLACE INTO users (user_id, points) VALUES (?, ?)', (user_id, points))
        
        # Close betting for the match
        cursor.execute('UPDATE matches SET closed = 1 WHERE match_id = ?', (match_id,))
        conn.commit()

def get_match_result(match_id):
    with db_lock, get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute('SELECT match_name, team1, team2, result FROM matches WHERE match_id = ?', (match_id,))
        match = cursor.fetchone()
        return match

def close_betting(match_id):
    with db_lock, get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute('UPDATE matches SET closed = 1 WHERE match_id = ?', (match_id,))
        conn.commit()

def open_betting(match_id):
    with db_lock, get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute('UPDATE matches SET closed = 0 WHERE match_id = ?', (match_id,))
        conn.commit()

def is_betting_closed(match_id):
    with db_lock, get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute('SELECT closed FROM matches WHERE match_id = ?', (match_id,))
        result = cursor.fetchone()
        return result[0] == 1 if result else False

def cancel_bet(user_id, bet_id):
    with db_lock, get_db_connection() as conn:
        cursor = conn.cursor()

        # Retrieve the bet details
        cursor.execute('SELECT match_id, team, amount, timestamp FROM bets WHERE bet_id = ? AND user_id = ?', (bet_id, user_id))
        bet = cursor.fetchone()
        if not bet:
            return False
        
        match_id, team, amount, bet_timestamp = bet

         # Check if the cancellation window has passed
        if datetime.now() - datetime.strptime(bet_timestamp, '%Y-%m-%d %H:%M:%S') > CANCELATION_WINDOW:
            return False  # Cancellation window has passed

        # Check if betting is closed for the match
        cursor.execute('SELECT team1, team2, closed FROM matches WHERE match_id = ?', (match_id,))
        match = cursor.fetchone()
        team1, team2, closed = match
        if closed:
            return False

        # Remove the bet
        cursor.execute('DELETE FROM bets WHERE bet_id = ? AND user_id = ?', (bet_id, user_id))
        
        # Update total bet amounts
        if team == team1:
            cursor.execute('UPDATE matches SET team1_total_bet = team1_total_bet - ? WHERE match_id = ?', (amount, match_id))
        if team == team2:
            cursor.execute('UPDATE matches SET team2_total_bet = team2_total_bet - ? WHERE match_id = ?', (amount, match_id))

        # Refund the user points
        cursor.execute('SELECT points FROM users WHERE user_id = ?', (user_id,))
        user_points = cursor.fetchone()[0]
        updated_points = user_points + amount
        cursor.execute('UPDATE users SET points = ? WHERE user_id = ?', (updated_points, user_id))

        # Update dividends
        cursor.execute('SELECT team1_total_bet, team2_total_bet FROM matches WHERE match_id = ?', (match_id,))
        totals = cursor.fetchone()
        if not totals:
            return False
        
        team1_total_bet, team2_total_bet = totals
        total_bet = team1_total_bet + team2_total_bet

        if total_bet == 0:
            return False
        
        team1_dividend = total_bet / team1_total_bet if team1_total_bet > 0 else 1.0
        team2_dividend = total_bet / team2_total_bet if team2_total_bet > 0 else 1.0

        cursor.execute('UPDATE matches SET team1_dividend = ?, team2_dividend = ? WHERE match_id = ?', (team1_dividend, team2_dividend, match_id))
        
        conn.commit()
        return True

# Bot events
@bot.event
async def on_ready():
    initialize_database()
    print(f'Logged in as {bot.user.name}')

# Bot commands for matches and betting 명령어 수정은 전부 여기서 위는 건들지 말아주세요
@bot.tree.command(name="addmatch", description="Add a new match")
@app_commands.checks.has_permissions(administrator=True)
async def add_match_command(ctx, match_name: str, team1: str, team2: str, date: str):
    add_match(match_name, team1, team2, datetime.strptime(date, '%Y-%m-%d %H:%M:%S'))
    await ctx.send(f'***경기: {match_name}*** {team1} vs {team2} 일자: {date} 배당 {1.0} / {1.0} 추가되었습니다.')

@bot.tree.command(name="경기", description="다가오는 경기를 확인합니다.")
async def matches(interaction: discord.Interaction):
    matches = get_matches()
    if not matches:
        await interaction.response.send_message('다가오는 경기가 없습니다.')
        return
    message = '다가오는 경기:\n'
    for match in matches:
        match_id, match_name, team1, team2, date, result, team1_dividend, team2_dividend, closed, team1_total_bet, team2_total_bet = match
        message += (f'***ID: {match_id}, 경기: {match_name}, 팀: {team1} vs {team2}, Date: {date}***'
                    f'\n배당: {team1_dividend} ({team1}) / {team2_dividend} ({team2})'
                    f'\n총 베팅 금액: {team1_total_bet} ({team1}) / {team2_total_bet} ({team2})'
                    f'\n베팅 가능 여부: {"닫힘" if closed else "열림"}\n')
    await interaction.response.send_message(message)

@bot.tree.command(name="베팅", description="경기에 포인트를 베팅합니다.")
async def bet(interaction: discord.Interaction, match_id: int, team: str, amount: int):
    user_id = str(interaction.user.id)
    points = get_user_points(user_id)
    if points < amount:
        await interaction.response.send_message('베팅에 필요한 포인트가 부족합니다.')
        return
    if amount > MAX_TOTAL_BET_PER_USER:
        await interaction.response.send_message(f'베팅 금액은 {MAX_TOTAL_BET_PER_USER}포인트를 초과할 수 없습니다.')
        return
    success, bet_id = place_bet(user_id, match_id, team, amount)
    if not success:
        await interaction.response.send_message('이 경기는 베팅이 닫혔거나 총 베팅 금액을 초과하였습니다.')
        return
    set_user_points(user_id, points - amount)
    await interaction.response.send_message(f'{team}에 {amount} 포인트 베팅 - 매치 번호: {match_id}. 베팅 번호: {bet_id}')


@bot.tree.command(name="베팅취소", description="베팅을 취소합니다.")
async def cancel_bet_command(interaction: discord.Interaction, bet_id: int):
    user_id = str(interaction.user.id)
    if cancel_bet(user_id, bet_id):
        await interaction.response.send_message(f'배팅 번호 {bet_id} 취소되었습니다.')
    else:
        await interaction.response.send_message(f'배팅 번호 {bet_id} 를 취소할 수 없습니다. 베팅 시간이 5분을 넘었거나 베팅 번호가 잘못되었습니다.')


@bot.tree.command(name="closebets", description="매치에 대한 배팅을 마감합니다.")
@app_commands.checks.has_permissions(administrator=True)
async def close_bets(interaction: discord.Interaction, match_id: int):
    close_betting(match_id)
    
    conn = sqlite3.connect('points.db')
    cursor = conn.cursor()
    
    cursor.execute('SELECT team1, team2, team1_total_bet, team2_total_bet, team1_dividend, team2_dividend FROM matches WHERE match_id = ?', (match_id,))
    match = cursor.fetchone()
    
    if not match:
        await interaction.response.send_message(f'매치 번호 {match_id}에 해당하는 경기를 찾지 못했습니다.')
        conn.close()
        return
    
    team1, team2, team1_total_bet, team2_total_bet, team1_dividend, team2_dividend = match
    conn.close()
    
    await interaction.response.send_message(f'매치 번호 {match_id}에 대한 배팅이 마감되었습니다.\n'
                                            f'팀 {team1}: 총 베팅 금액 = {team1_total_bet}, 배당 = {team1_dividend}\n'
                                            f'팀 {team2}: 총 베팅 금액 = {team2_total_bet}, 배당 = {team2_dividend}')

@close_bets.error
async def close_bets_error(interaction: discord.Interaction, error):
    if isinstance(error, app_commands.MissingPermissions):
        await interaction.response.send_message("이 명령어를 사용하려면 관리자 권한이 필요합니다.", ephemeral=True)
    else:
        await interaction.response.send_message("명령어 실행 중 오류가 발생했습니다.", ephemeral=True)


@bot.tree.command(name="openbets", description="매치에 대한 베팅을 엽니다.")
@app_commands.checks.has_permissions(administrator=True)
async def open_bet(interaction: discord.Interaction, match_id: int):
    open_betting(match_id)
    await interaction.response.send_message(f'Betting opened for match ID {match_id}.')

@open_bet.error
async def open_bet_error(interaction: discord.Interaction, error):
    if isinstance(error, app_commands.MissingPermissions):
        await interaction.response.send_message("이 명령어를 사용하려면 관리자 권한이 필요합니다.", ephemeral=True)
    else:
        await interaction.response.send_message("명령어 실행 중 오류가 발생했습니다.", ephemeral=True)


@bot.tree.command(name="setresult", description="매치 결과를 설정합니다.")
@app_commands.checks.has_permissions(administrator=True)
async def set_result(interaction: discord.Interaction, match_id: int, winning_team: str):
    with sqlite3.connect('points.db') as conn:
        cursor = conn.cursor()
        # Check if the match exists
        cursor.execute('SELECT team1, team2 FROM matches WHERE match_id = ?', (match_id,))
        match = cursor.fetchone()
        if not match:
            await interaction.response.send_message(f'매치 번호 {match_id}에 해당하는 경기를 찾지 못했습니다.')
            return
        
        team1, team2 = match
        if winning_team not in (team1, team2):
            await interaction.response.send_message(f'팀 {winning_team} 경기 번호 {match_id}에 없습니다.')
            return
        
        # Close the match and distribute winnings
        close_match(match_id, winning_team)
        await interaction.response.send_message(f'경기 번호 {match_id} 결과 {winning_team} 승리. 정산되었습니다.')

@set_result.error
async def set_result_error(interaction: discord.Interaction, error):
    if isinstance(error, app_commands.MissingPermissions):
        await interaction.response.send_message("이 명령어를 사용하려면 관리자 권한이 필요합니다.", ephemeral=True)
    else:
        await interaction.response.send_message("명령어 실행 중 오류가 발생했습니다.", ephemeral=True)


@bot.tree.command(name="결과", description="매치 결과를 확인합니다.")
async def result(interaction: discord.Interaction, match_id: int):
    match = get_match_result(match_id)
    if not match:
        await interaction.response.send_message(f'No match found with ID {match_id}.')
        return
    match_name, team1, team2, result = match
    if result:
        await interaction.response.send_message(f'경기: {match_name}\n팀: {team1} vs {team2}\n결과: {result}')
    else:
        await interaction.response.send_message(f'경기: {match_name}\n팀: {team1} vs {team2}\n결과: 경기가 완료되지 않았습니다.')


@bot.tree.command(name="포인트", description="사용자의 포인트를 확인합니다.")
async def points(interaction: discord.Interaction, user: discord.Member = None):
    user = user or interaction.user
    points = get_user_points(str(user.id))
    await interaction.response.send_message(f'{user.display_name}님은 {points}포인트를 보유 중입니다.')

# 포인트 확인
@bot.tree.command(name="포인트확인", description="다른 사용자의 포인트를 확인합니다.")
@app_commands.checks.has_permissions(administrator=True)
@app_commands.describe(member="확인할 사용자")
async def check_points(interaction: discord.Interaction, member: discord.Member):
    user_id = str(member.id)
    points = get_user_points(user_id)
    await interaction.response.send_message(f'{member.display_name}님은 {points}포인트를 보유 중입니다.')

@check_points.error
async def check_points_error(interaction: discord.Interaction, error):
    if isinstance(error, app_commands.MissingPermissions):
        await interaction.response.send_message("이 명령어를 사용하려면 관리자 권한이 필요합니다.", ephemeral=True)
    else:
        await interaction.response.send_message("명령어 실행 중 오류가 발생했습니다.", ephemeral=True)



@bot.tree.command(name="addpoints", description="사용자에게 포인트를 추가합니다.")
@app_commands.checks.has_permissions(administrator=True)
async def add_points(interaction: discord.Interaction, user: discord.Member, amount: int):
    user_id = str(user.id)
    current_points = get_user_points(user_id)
    set_user_points(user_id, current_points + amount)
    await interaction.response.send_message(f'{amount}포인트를 {user.display_name}님에게 추가하였습니다.')

@add_points.error
async def add_points_error(interaction: discord.Interaction, error):
    if isinstance(error, app_commands.MissingPermissions):
        await interaction.response.send_message("이 명령어를 사용하려면 관리자 권한이 필요합니다.", ephemeral=True)
    else:
        await interaction.response.send_message("명령어 실행 중 오류가 발생했습니다.", ephemeral=True)


@bot.tree.command(name="removepoints", description="사용자의 포인트를 제거합니다.")
@app_commands.checks.has_permissions(administrator=True)
async def remove_points(interaction: discord.Interaction, user: discord.Member, amount: int):
    user_id = str(user.id)
    current_points = get_user_points(user_id)
    
    if current_points < amount:
        await interaction.response.send_message(f'{user.display_name}님의 포인트가 부족합니다. 현재 포인트: {current_points}포인트')
        return
    
    set_user_points(user_id, max(0, current_points - amount))
    await interaction.response.send_message(f'{user.display_name}님의 {amount}포인트를 제거하였습니다. 현재 포인트: {current_points - amount}포인트')

@remove_points.error
async def remove_points_error(interaction: discord.Interaction, error):
    if isinstance(error, app_commands.MissingPermissions):
        await interaction.response.send_message("이 명령어를 사용하려면 관리자 권한이 필요합니다.", ephemeral=True)
    else:
        await interaction.response.send_message("명령어 실행 중 오류가 발생했습니다.", ephemeral=True)



@bot.tree.command(name="도움말", description="도움말을 제공합니다.")
async def help(interaction: discord.Interaction):
    await interaction.response.send_message('''
    **도움말**
    `/포인트` - 포인트 확인
    `/경기` - 다가오는 경기 목록
    `/베팅 <match_id> <team> <amount>` - 베팅
    `/베팅취소 <bet_id>` - 베팅 취소
    `/결과 <match_id>` - 경기 결과 확인
    `/내전개설 <내전_이름>` - 내전 개설
    `/팀 <내전_이름>` - 팀 상태 조회
    `/팀마감 <내전_이름>` - 팀 마감
    `/떠나기 <내전_이름>` - 팀 참가 취소
    `/내전종료 <내전_이름> <이긴_팀>` - 내전 종료 및 승패 기록
    `/전적 [@사용자]` - 전적 조회
    `/티어표` - 티어표          
    `/도움말` - 도움말
                                            
    **관리자 명령어:**
    `/addpoints <user> <amount>` - 포인트 추가
    `/포인트확인 <user>` - 포인트 확인
    `/set_mmr <user> <new_mmr>` - MMR 설정
    `/addmatch <match_name> <team1> <team2> <date>` - 경기 추가
    `<date>` 형식: `YYYY-MM-DD HH:MM:SS`
    `/closebets <match_id>` - 베팅 마감
    `/openbets <match_id>` - 베팅 열기
    `/setresult <match_id> <winning_team>` - 경기 결과 설정
    `/removepoints <user> <amount>` - 포인트 제거
    ''', ephemeral=True)



#-------- 내전 관련 명령어 --------
# 내전 개설 명령어
# 내전 개설 명령어
@bot.tree.command(name="내전개설", description="내전을 개설합니다.")
async def start_match(interaction: discord.Interaction, match_name: str):
    global team_closed
    team_closed[match_name] = False  # 팀 참가를 열림 상태로 설정

    button_team1 = Button(label="팀1 참가", style=discord.ButtonStyle.primary)
    button_team2 = Button(label="팀2 참가", style=discord.ButtonStyle.primary)

    async def join_team1(button_interaction: discord.Interaction):
        await join_team(button_interaction, match_name, 1)
    
    async def join_team2(button_interaction: discord.Interaction):
        await join_team(button_interaction, match_name, 2)

    button_team1.callback = join_team1
    button_team2.callback = join_team2

    view = View()
    view.add_item(button_team1)
    view.add_item(button_team2)

    await interaction.response.send_message(f"'{match_name}' 내전에 버튼을 눌러 팀에 참가하세요.:", view=view)

# 팀 참가 함수
async def join_team(interaction: discord.Interaction, match_name: str, team: int):
    if team_closed.get(match_name, True):
        await interaction.response.send_message("더 이상 팀 참가가 불가능합니다.", ephemeral=True)
        return

    user_id = interaction.user.id
    with db_lock:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute('''
            INSERT INTO teams (match_name, user_id, team)
            VALUES (?, ?, ?)
            ON CONFLICT(match_name, user_id) DO UPDATE SET team = excluded.team
        ''', (match_name, user_id, team))
        
        # 팀 인원 수 확인
        cursor.execute('SELECT COUNT(*) FROM teams WHERE match_name = ? AND team = ?', (match_name, team))
        team_count = cursor.fetchone()[0]
        conn.commit()
        conn.close()
    
    await interaction.response.send_message(f"'{match_name}' 팀{team} 참가 완료!", ephemeral=True)

    # 팀 인원이 5명에 도달하면 알림 보내기
    if team_count == 5:
        await interaction.channel.send(f"'{match_name}' 팀{team}의 인원이 5명에 도달했습니다!")



# 팀 상태 조회 명령어
@bot.tree.command(name="팀", description="내전의 팀 상태를 확인합니다.")
async def team_status(interaction: discord.Interaction, match_name: str):
    await interaction.response.defer()

    with db_lock:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT user_id, team FROM teams WHERE match_name = ?", (match_name,))
        rows = cursor.fetchall()
        conn.close()

    if not rows:
        await interaction.followup.send("해당 내전에 참가한 사용자가 없습니다.")
        return

    teams = {1: [], 2: []}
    team_mmr = {1: [], 2: []}

    guild = interaction.guild

    tasks = []
    for row in rows:
        user_id, team = row
        task = fetch_user_data(guild, user_id, team, teams, team_mmr)
        tasks.append(task)

    await asyncio.gather(*tasks)

    avg_mmr_team1 = sum(team_mmr[1]) / len(team_mmr[1]) if team_mmr[1] else BASE_MMR
    avg_mmr_team2 = sum(team_mmr[2]) / len(team_mmr[2]) if team_mmr[2] else BASE_MMR

    team1_members = "\n".join(teams[1])
    team2_members = "\n".join(teams[2])

    await interaction.followup.send(f"**'{match_name}' 팀1:**\n{team1_members}\n평균 MMR: {avg_mmr_team1:.2f}\n\n**'{match_name}' 팀2:**\n{team2_members}\n평균 MMR: {avg_mmr_team2:.2f}")

async def fetch_user_data(guild, user_id, team, teams, team_mmr):
    user = await guild.fetch_member(user_id)
    display_name = user.nick if user.nick else user.display_name

    with db_lock:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT mmr FROM records WHERE user_id = ?", (user_id,))
        mmr = cursor.fetchone()
        conn.close()

    mmr_value = mmr[0] if mmr else BASE_MMR
    teams[team].append(display_name + " " + str(mmr_value))
    team_mmr[team].append(mmr_value)


# 팀원 추가 명령어
@bot.tree.command(name="팀원추가", description="내전에 팀원을 추가합니다.")
@app_commands.checks.has_permissions(administrator=True)
async def add_team_member(interaction: discord.Interaction, match_name: str, member: discord.Member, team: int):
    if team not in [1, 2]:
        await interaction.response.send_message("팀 번호는 1 또는 2이어야 합니다.", ephemeral=True)
        return
    
    user_id = member.id
    with db_lock:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute('''
            INSERT INTO teams (match_name, user_id, team)
            VALUES (?, ?, ?)
            ON CONFLICT(match_name, user_id) DO UPDATE SET team = excluded.team
        ''', (match_name, user_id, team))
        conn.commit()
        conn.close()
    
    await interaction.response.send_message(f"{member.display_name}님을 '{match_name}' 내전의 팀{team}에 추가했습니다.")

@add_team_member.error
async def add_team_member_error(interaction: discord.Interaction, error):
    if isinstance(error, app_commands.MissingPermissions):
        await interaction.response.send_message("이 명령어를 사용하려면 관리자 권한이 필요합니다.", ephemeral=True)
    else:
        await interaction.response.send_message("명령어 실행 중 오류가 발생했습니다.", ephemeral=True)

@bot.tree.command(name="팀원제거", description="내전에서 팀원을 제거합니다.")
@app_commands.checks.has_permissions(administrator=True)
async def remove_team_member(interaction: discord.Interaction, match_name: str, member: discord.Member):
    user_id = member.id
    with db_lock:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("DELETE FROM teams WHERE match_name = ? AND user_id = ?", (match_name, user_id))
        rows_affected = cursor.rowcount
        conn.commit()
        conn.close()
    
    if rows_affected > 0:
        await interaction.response.send_message(f"{member.display_name}님을 '{match_name}' 내전에서 제거했습니다.")
    else:
        await interaction.response.send_message(f"{member.display_name}님은 '{match_name}' 내전에 참가하고 있지 않습니다.", ephemeral=True)

@remove_team_member.error
async def remove_team_member_error(interaction: discord.Interaction, error):
    if isinstance(error, app_commands.MissingPermissions):
        await interaction.response.send_message("이 명령어를 사용하려면 관리자 권한이 필요합니다.", ephemeral=True)
    else:
        await interaction.response.send_message("명령어 실행 중 오류가 발생했습니다.", ephemeral=True)



# 팀 마감 명령어
@bot.tree.command(name="팀마감", description="내전 팀 참가를 마감합니다.")
async def close_teams(interaction: discord.Interaction, match_name: str):
    await interaction.response.defer()
    async with bot.team_lock:
        global team_closed
        team_closed[match_name] = True
        
        with db_lock:
            conn = get_db_connection()
            cursor = conn.cursor()
            cursor.execute("SELECT user_id, team FROM teams WHERE match_name = ?", (match_name,))
            rows = cursor.fetchall()
            team_mmr = {1: [], 2: []}
            for row in rows:
                user_id, team = row
                cursor.execute("SELECT mmr FROM records WHERE user_id = ?", (user_id,))
                mmr = cursor.fetchone()
                if mmr:
                    team_mmr[team].append(mmr[0])
                else:
                    team_mmr[team].append(BASE_MMR)

            avg_mmr_team1 = sum(team_mmr[1]) / len(team_mmr[1]) if team_mmr[1] else BASE_MMR
            avg_mmr_team2 = sum(team_mmr[2]) / len(team_mmr[2]) if team_mmr[2] else BASE_MMR
            
            conn.close()
        
        await interaction.followup.send(f"'{match_name} 내전 팀 참가가 종료되었습니다'.\n"
                                                f"팀1 평균MMR: {avg_mmr_team1:.2f}\n"
                                                f"팀2 평균MMR: {avg_mmr_team2:.2f}")

# 팀 참가 취소 명령어
@bot.tree.command(name="떠나기", description="내전을 떠납니다.")
async def leave(interaction: discord.Interaction, match_name: str):
    user_id = interaction.user.id
    with db_lock:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("DELETE FROM teams WHERE match_name = ? AND user_id = ?", (match_name, user_id))
        conn.commit()
        conn.close()
    await interaction.response.send_message(f"{interaction.user.display_name}님이 '{match_name}' 내전을 떠났습니다.")


# 내전 종료 및 승패 기록 명령어
@bot.tree.command(name="내전종료", description="내전을 종료하고 결과를 기록합니다.")
async def end_match(interaction: discord.Interaction, match_name: str, winning_team: int):
    if winning_team not in (1, 2):
        await interaction.response.send_message("올바르지 않은 팀 번호입니다. 1 또는 2를 입력해주세요.")
        return

    with db_lock:
        conn = get_db_connection()
        cursor = conn.cursor()

        # Calculate average MMR for the entire match
        cursor.execute("SELECT user_id, team FROM teams WHERE match_name = ?", (match_name,))
        rows = cursor.fetchall()
        total_mmr = []
        for row in rows:
            user_id = row[0]
            cursor.execute("SELECT mmr FROM records WHERE user_id = ?", (user_id,))
            mmr = cursor.fetchone()
            if mmr:
                total_mmr.append(mmr[0])
            else:
                total_mmr.append(BASE_MMR)

        avg_mmr_match = sum(total_mmr) / len(total_mmr) if total_mmr else BASE_MMR

        for row in rows:
            user_id, team = row
            cursor.execute("SELECT mmr, streak FROM records WHERE user_id = ?", (user_id,))
            user_data = cursor.fetchone()
            if user_data:
                user_mmr, streak = user_data
            else:
                user_mmr, streak = BASE_MMR, 0

            # Determine MMR change based on player's MMR vs match average MMR
            mmr_diff = user_mmr - avg_mmr_match
            if mmr_diff > 0:
                mmr_change = MMR_CHANGE - int(mmr_diff / 100)
            else:
                mmr_change = MMR_CHANGE + int(mmr_diff / 100)
            
            if mmr_change < 0:
                mmr_change = 1

            if team == winning_team:
                new_streak = streak + 1 if streak > 0 else 1
                if new_streak >= 3:
                    streak_multiplier = (abs(new_streak) - 2) / 10 + 1 
                    mmr_change = int(mmr_change * streak_multiplier) # Increase MMR change based on winning streak length
                cursor.execute('''
                    INSERT INTO records (user_id, wins, losses, mmr, streak)
                    VALUES (?, 1, 0, ?, ?)
                    ON CONFLICT(user_id) DO UPDATE SET 
                        wins = wins + 1,
                        mmr = mmr + ?,
                        streak = ?
                ''', (user_id, BASE_MMR + mmr_change, new_streak, mmr_change, new_streak))
            else:
                new_streak = streak - 1 if streak < 0 else -1
                if new_streak <= -3:
                    streak_multiplier = (abs(new_streak) - 2) / 10 + 1  # Increase MMR change based on losing streak length
                    mmr_change = int(mmr_change * streak_multiplier)
                cursor.execute('''
                    INSERT INTO records (user_id, wins, losses, mmr, streak)
                    VALUES (?, 0, 1, ?, ?)
                    ON CONFLICT(user_id) DO UPDATE SET 
                        losses = losses + 1,
                        mmr = mmr - ?,
                        streak = ?
                ''', (user_id, BASE_MMR - mmr_change, new_streak, mmr_change, new_streak))
        conn.commit()
        cursor.execute("DELETE FROM teams WHERE match_name = ?", (match_name,))
        conn.commit()
        conn.close()
    await interaction.response.send_message(f"내전 '{match_name}' 종료. 팀{winning_team} 승리!")


@bot.tree.command(name="전적", description="사용자의 전적을 확인합니다.")
async def record(interaction: discord.Interaction, member: discord.Member = None):
    member = member or interaction.user
    user_id = member.id
    with db_lock:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT wins, losses, mmr FROM records WHERE user_id = ?", (user_id,))
        row = cursor.fetchone()
        conn.close()
    if row:
        wins, losses, mmr = row
        await interaction.response.send_message(f"{member.display_name} - 승: {wins}, 패: {losses}, MMR: {mmr}")
    else:
        await interaction.response.send_message(f"{member.display_name}님의 기록이 없습니다.")


# 티어표 명령어
@bot.tree.command(name="티어표", description="모든 유저의 티어를 확인합니다.")
async def tier_list(interaction: discord.Interaction):
    await interaction.response.defer()
    tiers = [
        "Iron IV", "Iron III", "Iron II", "Iron I",
        "Bronze IV", "Bronze III", "Bronze II", "Bronze I",
        "Silver IV", "Silver III", "Silver II", "Silver I",
        "Gold IV", "Gold III", "Gold II", "Gold I",
        "Platinum IV", "Platinum III", "Platinum II", "Platinum I",
        "Emerald IV", "Emerald III", "Emerald II", "Emerald I",
        "Diamond IV", "Diamond III", "Diamond II", "Diamond I",
        "Master", "Grandmaster", "Challenger"
    ]

    def get_tier(mmr):
        if mmr < 500:
            return tiers[0]
        elif mmr >= 3400:
            return tiers[-1]
        else:
            # Calculate tier index based on MMR
            # 100 mmr per tier
            if mmr - 500 < 0:
                return tiers[0]
            return tiers[(mmr - 500) // 100 + 1]


            #index = (mmr - 600) // 100
            #return tiers[index]

    with db_lock:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT user_id, mmr FROM records ORDER BY mmr DESC")
        rows = cursor.fetchall()
        conn.close()

    if not rows:
        await interaction.followup.send("등록된 유저가 없습니다.")
        return

    tier_list = []
    guild = interaction.guild

    for row in rows:
        user_id, mmr = row
        try:
            user = await guild.fetch_member(user_id)
        except discord.errors.NotFound:
            continue

        display_name = user.nick if user.nick else user.display_name
        tier = get_tier(mmr)
        tier_list.append(f"{display_name} - {tier} ({mmr} MMR)")

    tier_list_message = "\n".join(tier_list)
    await interaction.followup.send(f"**티어표**\n{tier_list_message}")

@tier_list.error
async def tier_list_error(interaction: discord.Interaction, error):
    await interaction.followup.send("명령어 실행 중 오류가 발생했습니다.", ephemeral=True)


# 관리자 MMR 설정 명령어
@bot.tree.command(name="set_mmr", description="사용자의 MMR을 설정합니다.")
@app_commands.checks.has_permissions(administrator=True)
async def set_mmr(interaction: discord.Interaction, member: discord.Member, new_mmr: int):
    user_id = member.id
    with db_lock:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute('''
            INSERT INTO records (user_id, wins, losses, mmr)
            VALUES (?, 0, 0, ?)
            ON CONFLICT(user_id) DO UPDATE SET mmr = ?
        ''', (user_id, new_mmr, new_mmr))
        conn.commit()
        conn.close()
    await interaction.response.send_message(f"{member.display_name}의 MMR이 {new_mmr}로 조정되었습니다.")

@set_mmr.error
async def set_mmr_error(interaction: discord.Interaction, error):
    if isinstance(error, app_commands.MissingPermissions):
        await interaction.response.send_message("이 명령어를 사용하려면 관리자 권한이 필요합니다.", ephemeral=True)
    else:
        await interaction.response.send_message("명령어 실행 중 오류가 발생했습니다.", ephemeral=True)


bot.run(TOKEN)
