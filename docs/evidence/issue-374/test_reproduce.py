"""Check the research sampler's missing-data and interpolation semantics offline."""
from datetime import timedelta
import unittest

import numpy as np

from reproduce import RUN, route, sample


class SamplingTests(unittest.TestCase):
    def setUp(self):
        lat = np.array([[34., 34.], [33., 33.]])
        lon = np.array([[130., 131.], [130., 131.]])
        values = np.array([[20., 40.], [60., 80.]])
        self.records = {(RUN + timedelta(hours=h), 850, 'rh'): (values+h, lat, lon)
                        for h in (0, 3, 6)}

    def test_bilinear_and_time_on_descending_latitude(self):
        self.assertEqual(sample(self.records, 'rh', 850, RUN+timedelta(hours=1.5), 33.5, 130.5, 3), 51.5)
        self.assertEqual(sample(self.records, 'rh', 850, RUN, 34., 130., 3), 20.)

    def test_missing_scheduled_endpoint_does_not_bridge_to_later_time(self):
        del self.records[RUN+timedelta(hours=3), 850, 'rh']
        self.assertIsNone(sample(self.records, 'rh', 850, RUN+timedelta(hours=1.5), 33.5, 130.5, 3))

    def test_missing_corner_stays_missing(self):
        self.records[RUN, 850, 'rh'][0][0, 0] = np.nan
        self.assertIsNone(sample(self.records, 'rh', 850, RUN, 33.5, 130.5, 3))

    def test_no_spatial_or_time_extrapolation_or_missing_level_substitution(self):
        for when, lat, level in ((RUN, 35., 850), (RUN-timedelta(hours=1), 33.5, 850), (RUN, 33.5, 700)):
            self.assertIsNone(sample(self.records, 'rh', level, when, lat, 130.5, 3))

    def test_route_has_one_shared_waypoint_and_monotonic_distance(self):
        points = list(route())
        self.assertEqual(len(points), 49)
        self.assertTrue(all(a[0] < b[0] for a, b in zip(points, points[1:])))
        self.assertEqual(points[0][1:], (31.87712037682015, 131.4484495960596))
        self.assertEqual(points[-1][1:], (32.91714519596533, 129.9132553497481))


if __name__ == '__main__':
    unittest.main()
