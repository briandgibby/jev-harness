import importlib.util, pathlib, sys, unittest
root = pathlib.Path(sys.argv[1])
spec = importlib.util.spec_from_file_location('solution', root / 'solution.py')
solution = importlib.util.module_from_spec(spec)
spec.loader.exec_module(solution)
class Acceptance(unittest.TestCase):
    def test_positive(self): self.assertEqual(solution.add(2, 3), 5)
    def test_negative(self): self.assertEqual(solution.add(-5, 2), -3)
    def test_zero(self): self.assertEqual(solution.add(0, 0), 0)
unittest.main(argv=[sys.argv[0]], verbosity=2)
