#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""Tests for `ewerobot` package."""

import pytest

from ewerobot.ewerobot import EClient


@pytest.fixture
def eclient():
    return EClient(config={
        'APP_ID': 'YOUR_APP_ID',
        'APP_SECRET': 'YOUR_APP_SECRET'
    })


# def test_grant_token(eclient):
#     print(eclient.grant_token())
#
#
# def test_get_industry(eclient):
#     print(eclient.get_industry())


