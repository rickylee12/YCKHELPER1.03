# YCK Helper

## Introduction
YCK 베팅용 디스코드 봇

## Features
- 경기 추가
- 경기 목록 확인
- 베팅 및 취소
- 베팅 마감
- 결과 설정 및 분배
- 결과 확인

## Commands
### 관리자 명령어
- `!addmatch <match_name> <team1> <team2> <date> <team1_dividend> <team2_dividend>`
  - Adds a new match.
  - 예시: `!addmatch "Champions League Final" "Team A" "Team B" "2024-05-20 18:00:00" 1.5 2.0`

- `!closebets <match_id>`
  - Closes betting for a match and displays total bets and dividends for each team.
  - 예시: `!closebets 1`

- `!openbet <match_id>`
  - Opens betting for a match.
  - 예시: `!openbet 1`

- `!setresult <match_id> <winning_team>`
  - Sets the result of a match and distributes winnings.
  - 예시: `!setresult 1 "Team A"`

### 유저 명렁어
- `!경기`
  - 경기 목록

- `!베팅 <match_id> <team> <amount>`
  - 매치 번호에 해당하는 팀에 베팅
  - 예시: `!베팅 1 "Team A" 100`

- `!베팅취소 <bet_id>`
  - 베팅 번호에 해당하는 베팅 취소
  - 예시: `!베팅취소 1`

- `!결과 <match_id>`
  - 매치 번호에 해당하는 결과
  - 예시: `!결과 1`

## Setup
### Prerequisites
- Python 3.7+
- `discord.py` library

### Installation
1. Clone the repository:
   ```bash
   git clone https://github.com/Avokene/yckHelper.git
   cd yckHelper
