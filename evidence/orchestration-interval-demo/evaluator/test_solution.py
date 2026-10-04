import importlib.util, pathlib, sys, unittest
root = pathlib.Path(sys.argv[1])
spec = importlib.util.spec_from_file_location('solution', root / 'solution.py')
solution = importlib.util.module_from_spec(spec)
spec.loader.exec_module(solution)
class Acceptance(unittest.TestCase):
    def test_empty(self): self.assertEqual(solution.merge_intervals([]), [])
    def test_unsorted(self): self.assertEqual(solution.merge_intervals([(5, 7), (1, 3), (2, 6)]), [(1, 7)])
    def test_touching(self): self.assertEqual(solution.merge_intervals([(1, 3), (3, 5)]), [(1, 5)])
    def test_contained(self): self.assertEqual(solution.merge_intervals([(1, 8), (3, 5)]), [(1, 8)])
    def test_disjoint(self): self.assertEqual(solution.merge_intervals([(5, 6), (1, 2)]), [(1, 2), (5, 6)])
    def test_unmodified(self):
        items = [(3, 5), (1, 2)]
        solution.merge_intervals(items)
        self.assertEqual(items, [(3, 5), (1, 2)])
unittest.main(argv=[sys.argv[0]], verbosity=2)
