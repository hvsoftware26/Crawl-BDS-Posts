# Account model
from dataclasses import dataclass
from typing import Optional, List


@dataclass

class Info_data:
    row: int
    account_name: str
    path_chrome: str
    proxy: str
    email: str
    password: str
    twofa: str
    cookie: str
    token: str
    post_count: str
    api_key: str
    groups_list: Optional[List[str]] #List
    prompt: str
    id_chat: str
    token_tele: str
    cycle_total: int #Hours
    delay_get_post_gr: float #Min
    keywords_list: Optional[List[str]] #List
