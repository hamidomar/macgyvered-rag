import unittest

from turborefi.tools.calculators import (
    calc_ltv,
    calc_pmi_savings,
    calc_se_income,
    calc_w2_income,
)


class CalculatorTests(unittest.TestCase):
    def test_calc_w2_income_monthly(self):
        result = calc_w2_income(gross_income=12500, pay_frequency="monthly", gse="fnma")
        self.assertEqual(result["monthly_qualifying"], 12500)
        self.assertEqual(result["annual_income"], 150000)

    def test_calc_w2_income_biweekly(self):
        result = calc_w2_income(gross_income=3000, pay_frequency="biweekly", gse="fnma")
        self.assertEqual(result["monthly_qualifying"], 6500.0)
        self.assertEqual(result["annual_income"], 78000.0)

    def test_calc_w2_income_annual(self):
        result = calc_w2_income(gross_income=150000, pay_frequency="annual", gse="fnma")
        self.assertEqual(result["monthly_qualifying"], 12500.0)
        self.assertEqual(result["annual_income"], 150000.0)

    def test_calc_ltv(self):
        result = calc_ltv(loan_amount=450000, property_value=600000)
        self.assertEqual(result["ltv_ratio"], 0.75)
        self.assertEqual(result["ltv_percent"], 75.0)

    def test_calc_pmi_savings(self):
        result = calc_pmi_savings(current_pmi_monthly=185, years_remaining=22)
        self.assertEqual(result["monthly_savings"], 185)
        self.assertEqual(result["total_savings"], 48840)

    def test_calc_se_income(self):
        result = calc_se_income(
            yr1_net=95000,
            yr2_net=110000,
            depreciation=8000,
            depletion=0,
            gse="fnma",
        )
        self.assertEqual(result["qualifying_monthly"], 8875.0)


if __name__ == "__main__":
    unittest.main()
