"""The allocation rule: the parts must always reconstitute the whole."""

from decimal import Decimal

from django.test import SimpleTestCase

from expenses.splitting import allocate


class AllocateTests(SimpleTestCase):
    def test_even_split_that_divides_cleanly(self):
        self.assertEqual(allocate(Decimal("90.00"), [1, 1, 1]), [Decimal("30.00")] * 3)

    def test_the_indivisible_case(self):
        # The example the module exists for. Independent rounding gives
        # 99.99 or 100.02; this gives 100.00 with the paisa named.
        shares = allocate(Decimal("100.00"), [1, 1, 1])

        self.assertEqual(shares, [Decimal("33.34"), Decimal("33.33"), Decimal("33.33")])
        self.assertEqual(sum(shares), Decimal("100.00"))

    def test_weights_are_proportional(self):
        self.assertEqual(
            allocate(Decimal("100.00"), [3, 1]),
            [Decimal("75.00"), Decimal("25.00")],
        )

    def test_leftover_goes_to_the_largest_remainder(self):
        # 0.10 over weights 1,1,1,1,1,1,1 -> 1 paisa each, 3 left over,
        # and every remainder ties, so the first three positions take them.
        shares = allocate(Decimal("0.10"), [1] * 7)

        self.assertEqual(shares.count(Decimal("0.02")), 3)
        self.assertEqual(sum(shares), Decimal("0.10"))

    def test_the_sum_always_reconstitutes_the_whole(self):
        # The property, asserted broadly rather than on one lucky example.
        for total in ("0.01", "0.03", "10.00", "33.33", "100.00", "999.99"):
            for weights in ([1, 1, 1], [1, 2, 3], [7], [1] * 9, [5, 1, 1, 1]):
                with self.subTest(total=total, weights=weights):
                    self.assertEqual(sum(allocate(Decimal(total), weights)), Decimal(total))

    def test_a_single_participant_takes_everything(self):
        self.assertEqual(allocate(Decimal("41.67"), [1]), [Decimal("41.67")])

    def test_no_participants_allocates_nothing(self):
        self.assertEqual(allocate(Decimal("10.00"), []), [])

    def test_a_non_positive_weight_is_rejected(self):
        with self.assertRaises(ValueError):
            allocate(Decimal("10.00"), [1, 0])
