import json, pathlib, subprocess, sys, unittest
root = pathlib.Path(sys.argv[1])
CHILD = "import importlib.util, json, pathlib, sys\nroot = pathlib.Path(sys.argv[1])\nspec = importlib.util.spec_from_file_location('solution', root / 'solution.py')\nsolution = importlib.util.module_from_spec(spec)\nspec.loader.exec_module(solution)\nargs = json.load(sys.stdin)\nvalue = getattr(solution, sys.argv[2])(*args)\nsys.stdout.write(json.dumps({'value': value, 'args_after': args}))\n"
FUNCTION = 'add'
def invoke(*args):
    result = subprocess.run([sys.executable, '-B', '-c', CHILD, str(root), FUNCTION],
                            input=json.dumps(args), capture_output=True, text=True,
                            timeout=5, check=False, cwd=root)
    if result.returncode != 0:
        raise AssertionError('candidate subprocess exited before returning')
    try:
        payload = json.loads(result.stdout)
    except ValueError as exc:
        raise AssertionError('candidate subprocess did not return JSON') from exc
    if type(payload) is not dict or set(payload) != {'value', 'args_after'}:
        raise AssertionError('candidate subprocess returned an invalid result')
    return payload['value'], payload['args_after']
class Acceptance(unittest.TestCase):
    def test_positive(self): self.assertEqual(invoke(2, 3)[0], 5)
    def test_negative(self): self.assertEqual(invoke(-5, 2)[0], -3)
    def test_zero(self): self.assertEqual(invoke(0, 0)[0], 0)
result = unittest.TextTestRunner(stream=sys.stderr, verbosity=2).run(
    unittest.defaultTestLoader.loadTestsFromTestCase(Acceptance))
print(json.dumps({'schema_version': 1, 'tests_run': result.testsRun,
                  'failures': len(result.failures), 'errors': len(result.errors)},
                 sort_keys=True), flush=True)
sys.exit(0 if result.wasSuccessful() and result.testsRun > 0 else 1)
