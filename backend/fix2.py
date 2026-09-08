import re
c = open('tests/integration/test_e2e_semantic_verification.py').read()
c = c.replace('finish_reason=None', 'is_done=False')
c = c.replace('finish_reason="stop"', 'is_done=True')
open('tests/integration/test_e2e_semantic_verification.py', 'w').write(c)
