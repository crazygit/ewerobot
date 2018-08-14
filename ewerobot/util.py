# -*- coding: utf-8 -*-
import hashlib
import random
import string


def get_random_string(length=28, digits=True):
    """
    生成指定长度的随机字符串

    :param length: 随机字符串长度
    :param digits: 是否包含数字
    :return:
    """
    random_str = ''
    random_list = string.ascii_letters + string.digits if digits else string.ascii_letters
    for i in range(length):
        random_str += random.choice(random_list)
    return random_str


def get_signature(sign_param):
    """
    jsapi_ticket签名

    签名生成规则如下：参与签名的字段包括noncestr（随机字符串）, 有效的jsapi_ticket, timestamp（时间戳）, url（当前网页的URL，不包含#及其后面部分） 。对所有待签名参数按照字段名的ASCII 码从小到大排序（字典序）后，使用URL键值对的格式（即key1=value1&key2=value2…）拼接成字符串string1。这里需要注意的是所有参数名均为小写字符。对string1作sha1加密，字段名和字段值都采用原始值，不进行URL 转义。

    :param sign_param: 用于生成签名的参数

    :return: 签名信息
    """
    signature = '&'.join(['%s=%s' % (key.lower(), sign_param[key]) for key in sorted(sign_param)])
    return hashlib.sha1(signature.encode('utf-8')).hexdigest()
