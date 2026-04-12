import requests

def Get_Towfa(twofa):
    headers = {"accept": "*/*","accept-language": "en-US,en;q=0.9,vi;q=0.8","if-none-match": 'W/"12-XJOQd8Q1O2etfs04UznlJmRH/0c"',"priority": "u=1, i","referer": "https://2fa.live/","sec-ch-ua": '"Chromium";v="146", "Not-A.Brand";v="24", "Google Chrome";v="146"',"sec-ch-ua-mobile": "?0","sec-ch-ua-platform": '"Windows"',"sec-fetch-dest": "empty","sec-fetch-mode": "cors","sec-fetch-site": "same-origin","user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/146.0.0.0 Safari/537.36","cookie": "_ga=GA1.1.472578041.1775374886; _ga_R2SB88WPTD=GS2.1.s1775374886$o1$g1$t1775375885$j60$l0$h0",}

    try:
        response = requests.get(f"https://2fa.live/tok/{twofa}",headers=headers,timeout=15)
        response.raise_for_status()
        data = response.json()
        token = data.get("token")
        if not token:
            print(f"Không lấy được token 2FA, response: {data}")
            return False
        return token
    except Exception as e:
        print(f"Lỗi lấy 2FA: {e}")
        return False