"""Run on lab; stdout contains only quota data, never credentials or responses."""
import concurrent.futures
import datetime
import email.utils
import json
import math
import os
import ssl
import sys
from pathlib import Path
import time
import urllib.error
import urllib.request

def number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)

def normalize(provider, data):
    if provider == 'codex':
        windows = data.get('rate_limit') or {}
        week = next((w for w in windows.values() if isinstance(w, dict) and w.get('limit_window_seconds') == 604800), {})
        used, reset = week.get('used_percent'), week.get('reset_at')
    else:
        week = data.get('seven_day') or {}
        used, reset = week.get('utilization'), week.get('resets_at')
        try:
            reset = datetime.datetime.fromisoformat(reset.replace('Z', '+00:00')).timestamp()
        except (AttributeError, TypeError, ValueError, OverflowError):
            reset = None
    if not number(used) or used < 0:
        raise ValueError('weekly quota unavailable')
    result = {'used': used, 'reset': reset if number(reset) and reset > 0 else None}
    if provider == 'claude':
        for limit in data.get('limits') or []:
            if not isinstance(limit, dict) or limit.get('kind') != 'weekly_scoped':
                continue
            model = ((limit.get('scope') or {}).get('model') or {})
            if str(model.get('display_name', '')).casefold() != 'fable':
                continue
            value = limit.get('percent')
            if number(value) and value >= 0:
                result['fable'] = normalize('claude', {'seven_day': {'utilization': value, 'resets_at': limit.get('resets_at')}})
                break
    return result

class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None

def retry_after(value, now):
    if not value:
        return None
    try:
        delay = float(value)
    except ValueError:
        try:
            delay = email.utils.parsedate_to_datetime(value).timestamp() - now
        except (ValueError, TypeError, OverflowError):
            return None
    return max(0, math.ceil(delay)) if math.isfinite(delay) else None

def collect(provider):
    try:
        home = Path.home()
        if provider == 'codex':
            path = Path(os.environ.get('CODEX_HOME', str(home / '.codex'))) / 'auth.json'
            auth = json.loads(path.read_text())
            tokens = auth.get('tokens') or {}
            token = tokens.get('access_token')
            headers = {'Authorization': 'Bearer ' + token} if token else {}
            if tokens.get('account_id'):
                headers['ChatGPT-Account-Id'] = tokens['account_id']
            url = 'https://chatgpt.com/backend-api/wham/usage'
        else:
            path = Path(os.environ.get('CLAUDE_CONFIG_DIR', str(home / '.claude'))) / '.credentials.json'
            auth = json.loads(path.read_text())
            token = (auth.get('claudeAiOauth') or {}).get('accessToken')
            headers = {'Authorization': 'Bearer ' + token, 'anthropic-beta': 'oauth-2025-04-20'} if token else {}
            url = 'https://api.anthropic.com/api/oauth/usage'
        if not token:
            return {'error': '구독 로그인 필요'}
        headers['User-Agent'] = 'Herdr-Lab-Usage/1.0'
        request = urllib.request.Request(url, headers=headers)
        tls=ssl.create_default_context()
        tls.minimum_version=ssl.TLSVersion.TLSv1_2
        opener=urllib.request.build_opener(NoRedirect(),urllib.request.HTTPSHandler(context=tls))
        with opener.open(request, timeout=12) as response:
            raw = response.read(1048577)
        if len(raw) > 1048576:
            return {'error': '응답 크기 초과'}
        return normalize(provider, json.loads(raw))
    except FileNotFoundError:
        return {'error': 'lab 로그인 파일 없음'}
    except urllib.error.HTTPError as error:
        error.close()
        if error.code == 429:
            return {'error': 'Rate limited', 'status': 429, 'retry_after': retry_after(error.headers.get('Retry-After') if error.headers else None, time.time())}
        return {'error': {401: 'lab 재로그인 필요', 403: '사용량 조회 거부', 429: '요청 제한 · 잠시 후 재시도'}.get(error.code, '조회 오류 HTTP ' + str(error.code))}
    except ValueError:
        return {'error': '주간 사용량 확인 불가'}
    except Exception:
        return {'error': 'lab 사용량 연결 실패'}

def main():
    providers = [provider for provider in ('codex', 'claude') if not sys.argv[1:] or provider in sys.argv[1:]]
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        results = dict(zip(providers, pool.map(collect, providers)))
    print(json.dumps({'at': time.time(), **results}, ensure_ascii=False))

if __name__ == '__main__':
    main()
