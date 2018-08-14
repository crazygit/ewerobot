# -*- coding: utf-8 -*-
from werobot.client import ClientException


class AccessTokenInvalid(ClientException):
    """
    获取 access_token 时 AppSecret 错误，或者 access_token 无效

    错误码参考:
    https://mp.weixin.qq.com/wiki?t=resource/res_main&id=mp1433747234
    """


