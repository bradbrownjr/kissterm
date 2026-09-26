"""The `;PR:` answer to a Winlink `;PQ:` challenge, against wl2k-go's
own vectors (`fbb/secure_test.go`)."""

from kissterm._isolate import isolate

isolate()

import pytest  # noqa: E402

from kissterm.winlink.secure import login_response  # noqa: E402


@pytest.mark.parametrize(("challenge", "password", "expect"), [
    ("23753528", "FOOBAR", "72768415"),
    ("23753528", "FooBar", "95074758"),
])
def test_wl2k_go_vectors(challenge, password, expect):
    assert login_response(challenge, password) == expect
