# Provide a one-stop test.
# But if anything's really wrong, it's a bit of a mouthful.

test:
	pylint tsd.py
	pylint test_tsd.py
	./test_tsd.py
