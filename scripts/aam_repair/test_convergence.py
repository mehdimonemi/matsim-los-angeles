import tempfile, unittest
from pathlib import Path
from .convergence import assess

class ConvergenceTests(unittest.TestCase):
    def test_missing_data_never_converges(self):
        with tempfile.TemporaryDirectory() as d:self.assertFalse(assess(Path(d))['stable'])
    def test_score_and_demand_both_must_stabilize(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)
            (root/'run.scorestats.txt').write_text('ITERATION\tavg. EXECUTED\n'+''.join(f'{i}\t100\n' for i in range(10)))
            demand=root/'run.drt_customer_stats_aam_drt.csv'
            demand.write_text('iteration;rides\n'+''.join(f'{i};{100 if i<5 else 20}\n' for i in range(10)))
            self.assertFalse(assess(root)['stable'])
            demand.write_text('iteration;rides\n'+''.join(f'{i};20\n' for i in range(10)))
            self.assertTrue(assess(root)['stable'])
