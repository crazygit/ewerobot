# -*- coding: utf-8 -*-

"""Main module."""
import time
from functools import wraps

import requests
from flask import request, redirect, g, current_app
from requests.compat import json as _json
from retrying import retry
from werobot.client import Client, ClientException

from ewerobot.error import AccessTokenInvalid
from ewerobot.util import get_random_string, get_signature


def check_error(json):
    """
    检测微信公众平台返回值中是否包含错误的返回码。
    如果返回码提示有错误，抛出一个 :class:`ClientException` 异常。对于AccessToken失效的异常单独抛出，便于重试。
    """
    if "errcode" in json and json["errcode"] != 0:
        if json['errcode'] == 40001:
            raise AccessTokenInvalid("{}: {}".format(json["errcode"], json["errmsg"]))
        raise ClientException("{}: {}".format(json["errcode"], json["errmsg"]))
    return json


def retry_exception(exception):
    return isinstance(exception,
                      (AccessTokenInvalid, requests.exceptions.ReadTimeout, requests.exceptions.ConnectTimeout))


class EClient(Client):
    SNSAPI_BASE_SCOPE = 'snsapi_base'
    SNSAPI_USERINFO_SCOPE = 'snsapi_userinfo'

    def __init__(self, config=None):
        if config:
            self.init_app(config)

    def init_app(self, config):
        self.config = config
        self._token = None
        self._jsapi_ticket = None
        self.token_expires_at = None
        self.jsapi_ticket_expires_at = None

    def get_access_token(self, force=False):
        """
        判断现有的token是否过期。
        用户需要多进程或者多机部署可以手动重写这个函数
        来自定义token的存储，刷新策略。

        :param: 强制刷新access_token
        :return: 返回token
        """
        if not force and self._token:
            now = time.time()
            if self.token_expires_at - now > 60:
                return self._token
        json = self.grant_token()
        self._token = json["access_token"]
        self.token_expires_at = int(time.time()) + json["expires_in"]
        return self._token

    def get_jsapi_ticket(self, force=False):
        """
        判断现有的jsapi_ticket是否过期。
        用户需要多进程或者多机部署可以手动重写这个函数
        来自定义jsapi_ticket的存储，刷新策略。

        :param: 强制刷新sapi_ticket
        :return: jsapi_ticket
        """
        if not force and self._jsapi_ticket:
            now = time.time()
            if self.jsapi_ticket_expires_at - now > 60:
                return self._jsapi_ticket
        json = self.jsapi_ticket()
        self._jsapi_ticket = json["ticket"]
        self.jsapi_ticket_expires_at = int(time.time()) + json["expires_in"]
        return self._token

    @retry(stop_max_attempt_number=3, retry_on_exception=retry_exception)
    def request(self, method, url, **kwargs):
        if "params" not in kwargs:
            kwargs["params"] = {"access_token": self.token}
        # 如果是网页授权接口调用凭证时, 不需要基础支持的access_token去替换它
        elif "access_token" in kwargs["params"] and not kwargs.pop('oauth2_access_token', False):
            kwargs["params"]["access_token"] = self.token
        if isinstance(kwargs.get("data", ""), dict):
            body = _json.dumps(kwargs["data"], ensure_ascii=False)
            body = body.encode('utf8')
            kwargs["data"] = body
        r = requests.request(
            method=method,
            url=url,
            timeout=5,
            **kwargs
        )
        r.raise_for_status()
        json = r.json()
        try:
            if check_error(json):
                return json
        except AccessTokenInvalid as e:
            self.get_access_token(force=True)
            raise e

    def get_authorize_code_url(self, scope, redirect_uri, state=""):
        """
        微信网页授权，第1步: 生成用于重定向到微信的链接，以便获取code

        :param scope: 应用授权作用域，snsapi_base （不弹出授权页面，直接跳转，只能获取用户openid），snsapi_userinfo （弹出授权页面，可通过openid拿到昵称、性别、所在地。并且， 即使在未关注的情况下，只要用户授权，也能获取其信息 ）
        :param redirect_uri: 授权后重定向的回调链接地址
        :param state: 重定向后会带上state参数，开发者可以填写a-zA-Z0-9的参数值，最多128字节
        :return: 引导关注者打开的页面链接
        """
        params = (
            ("appid", self.appid),
            ("redirect_uri", redirect_uri),
            ("response_type", "code"),
            ("scope", scope),
            ("state", state)
        )
        r = requests.Request(method='GET',
                             url='https://open.weixin.qq.com/connect/oauth2/authorize#wechat_redirect',
                             params=params
                             )
        return r.prepare().url

    def get_oauth2_access_token_by_code(self, code):
        """
        微信网页授权，第2步: 通过code换取网页授权access_token
        :param code: 第1步中返回的code
        :return: access_token和open_id
        """
        return self.get('https://api.weixin.qq.com/sns/oauth2/access_token', params={
            'appid': self.appid,
            'secret': self.appsecret,
            'code': code,
            'grant_type': 'authorization_code'
        })

    def get_sns_user_info(self, oauth2_access_token, openid, lang='zh_CN'):
        """
        微信网页授权，第4步: 拉取用户信息(需scope为snsapi_userinfo)

        :param oauth2_access_token: 网页授权接口调用凭证,注意：此access_token与基础支持的access_token不同
        :param openid: 用户唯一标识
        :param lang: 返回国家地区语言版本，zh_CN 简体，zh_TW 繁体，en 英语
        :return: 用户信息
        """

        return self.get('https://api.weixin.qq.com/sns/userinfo',
                        params={
                            'access_token': oauth2_access_token,
                            'openid': openid,
                            'lang': lang,
                        },
                        oauth2_access_token=True,
                        )

    def sns_openid(self, func):
        """
        微信网页授权，获取用openid
        :param func:
        :return:
        """
        @wraps(func)
        def wrapper(*args, **kwargs):
            code = request.args.get('code', None)
            if not code:
                return redirect(
                    self.get_authorize_code_url(EClient.SNSAPI_BASE_SCOPE, request.url))
            access_token_info = self.get_oauth2_access_token_by_code(code)
            # 保存获取到的openid和oauth2_access_token到g
            g.openid = access_token_info.get('openid', None)
            g.oauth2_access_token = access_token_info.get('access_token', None)
            return func(*args, **kwargs)

        return wrapper

    def sns_userinfo(self, func):
        """
        微信网页授权，获取用户的基本信息
        :param func:
        :return:
        """
        @self.sns_openid
        @wraps(func)
        def wrapper(*args, **kwargs):
            g.user_info = self.get_sns_user_info(g.oauth2_access_token, g.openid)
            return func(*args, **kwargs)

        return wrapper

    def subscribe_required(self, subscribe_url=None):
        """
        微信网页授权, 发现当用户没有订阅公众号时，跳转到指定页面
        当没有传递subscribe_url参数时，默认跳转到Flask配置中的EWEROBOT_SUBSCRIBE_URL
        :param subscribe_url: 未关注公众号时重定向的链接
        :return:
        """

        def decorator(func):
            @self.sns_openid
            @wraps(func)
            def wrapper(*args, **kwargs):
                g.user_info = self.get_user_info(g.openid)
                if g.user_info['subscribe'] == 1:
                    return func(*args, **kwargs)
                return redirect(subscribe_url or current_app.config['EWEROBOT_SUBSCRIBE_URL'])

            return wrapper

        return decorator


    def set_industry(self, industry_id1, industry_id2):
        """
        消息管理 -  模板消息接口 - 设置所属行业

        行业代码可以参考: https://mp.weixin.qq.com/wiki?t=resource/res_main&id=mp1433751277

        :param industry_id1: 行业代码
        :param industry_id2: 行业代码
        :return:
        """
        return self.post('https://api.weixin.qq.com/cgi-bin/template/api_set_industry',
                         data={
                             'industry_id1': industry_id1,
                             'industry_id2': industry_id2,
                         })

    def get_industry(self):
        """
        消息管理 -  模板消息接口 - 获取设置的行业信息

        :return:
        """
        return self.get('https://api.weixin.qq.com/cgi-bin/template/get_industry')

    def api_add_template(self, template_id_short):
        """
        消息管理 -  模板消息接口 - 获得模板ID

        :param template_id_short: 模板库中模板的编号，有“TM**”和“OPENTMTM**”等形式

        :return:
        """
        return self.post('https://api.weixin.qq.com/cgi-bin/template/api_add_template',
                         data={
                             'template_id_short': template_id_short
                         })

    def get_all_private_template(self):
        """
        消息管理 -  模板消息接口 - 获取模板列表
        :return:
        """
        return self.get('https://api.weixin.qq.com/cgi-bin/template/get_all_private_template')

    def del_private_template(self, template_id):
        """
        消息管理 -  模板消息接口 - 删除模板
        :param template_id: 公众帐号下模板消息ID
        :return:
        """
        return self.post('https://api.weixin.qq.com/cgi-bin/template/del_private_template',
                         data={
                             'template_id': template_id
                         })


    def jsapi_ticket(self):
        """
        获取jsapi_ticket, jsapi_ticket是公众号用于调用微信JS接口的临时票据
        :return:
        """
        return self.get('https://api.weixin.qq.com/cgi-bin/ticket/getticket',
                        params={
                            'type': 'jsapi',
                            'access_token': self.token,
                        }
                        )


    def get_jssdk_config(self, url):
        """
        获取使用JS SDK的配置信息
        参考: https://mp.weixin.qq.com/wiki?t=resource/res_main&id=mp1421141115

        :param uri: 当前网页的URL，不包含#及其后面部分
        :return:
        """
        jsapi_ticket = self.get_jsapi_ticket()
        sign_param = {
            'noncestr': get_random_string(15, True),
            'jsapi_ticket': jsapi_ticket,
            'timestamp': int(time.time()),
            'url': url
        }
        config = {}
        config['appId'] = self.appid
        config['signature'] = get_signature(sign_param)
        config['timestamp'] = sign_param['timestamp']
        config['nonceStr'] = sign_param['noncestr']
        return config

    def send_all_text_message(self, content):
        '''
        群发文本消息，消息长度不能超过文本限制2048个字节

        :param msg: 消息正文
        :return: 返回的 JSON 数据包
        '''
        assert len(content.encode('utf-8')) < 2048
        return self.post(
            url='https://api.weixin.qq.com/cgi-bin/message/mass/sendall',
            data={
                'filter': {
                    'is_to_all': True,
                },
                'text': {
                    'content': content,
                },
                'msgtype': 'text',
                'clientmsgid': int(time.time() * 1000)

            },
            timeout=10,
        )
