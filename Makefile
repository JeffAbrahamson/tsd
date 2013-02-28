# Provide a one-stop test.
# But if anything's really wrong, it's a bit of a mouthful.
#
# pylint returns non-zero status at the least scent of
# inappropriateness, so don't let that stop us: return true.

test:
	pylint tsd.py || true
	pylint test_tsd.py || true
	./test_tsd.py
