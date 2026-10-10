import json, pathlib, subprocess, sys, unittest
root = pathlib.Path(sys.argv[1])
CHILD = "import importlib.util, json, pathlib, sys\nroot = pathlib.Path(sys.argv[1])\nspec = importlib.util.spec_from_file_location('solution', root / 'solution.py')\nsolution = importlib.util.module_from_spec(spec)\nspec.loader.exec_module(solution)\nargs = json.load(sys.stdin)\nvalue = getattr(solution, sys.argv[2])(*args)\ncontract_error = None\nif type(value) is not list:\n    contract_error = 'return_list'\nelif any(type(pair) is not tuple or len(pair) != 2 for pair in value):\n    contract_error = 'tuple_pair'\nelif any(type(endpoint) is not int for pair in value for endpoint in pair):\n    contract_error = 'integer_endpoints'\nif contract_error is not None:\n    sys.stdout.write(json.dumps({'contract_error': contract_error}))\nelse:\n    sys.stdout.write(json.dumps({'value': value, 'args_after': args}))\n"
FUNCTION = 'merge_intervals'
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
    if type(payload) is dict and set(payload) == {'contract_error'}:
        messages = {
            'return_list': 'merge_intervals must return a list',
            'tuple_pair': 'each interval must be a two-element tuple',
            'integer_endpoints': 'each interval must have integer endpoints'}
        error = payload['contract_error']
        if type(error) is str and error in messages:
            raise AssertionError(messages[error])
    if type(payload) is not dict or set(payload) != {'value', 'args_after'}:
        raise AssertionError('candidate subprocess returned an invalid result')
    return payload['value'], payload['args_after']
class Acceptance(unittest.TestCase):
    def test_empty(self): self.assertEqual(invoke([])[0], [])
    def test_single_interval(self): self.assertEqual(invoke([[1, 2]])[0], [[1, 2]])
    def test_unsorted(self): self.assertEqual(invoke([[5, 7], [1, 3], [2, 6]])[0], [[1, 7]])
    def test_touching(self): self.assertEqual(invoke([[1, 3], [3, 5]])[0], [[1, 5]])
    def test_contained(self): self.assertEqual(invoke([[1, 8], [3, 5]])[0], [[1, 8]])
    def test_disjoint(self): self.assertEqual(invoke([[5, 6], [1, 2]])[0], [[1, 2], [5, 6]])
    def test_unmodified(self):
        items = [[3, 5], [1, 2]]
        self.assertEqual(invoke(items)[1], [items])
result = unittest.TextTestRunner(stream=sys.stderr, verbosity=2).run(
    unittest.defaultTestLoader.loadTestsFromTestCase(Acceptance))
print(json.dumps({'schema_version': 1, 'tests_run': result.testsRun,
                  'failures': len(result.failures), 'errors': len(result.errors)},
                 sort_keys=True), flush=True)
sys.exit(0 if result.wasSuccessful() and result.testsRun > 0 else 1)
