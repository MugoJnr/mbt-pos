"""Portal report downloads keep shop formatting and omit hidden costs."""
import unittest

from backend.cloud.analytics_documents import (
    render_portal_csv,
    render_portal_html,
    render_portal_pdf,
    render_portal_xlsx,
    sheet_from_rows,
    summary_sheet,
)


class TestPortalReportDocuments(unittest.TestCase):
    def test_workbook_pdf_and_print_page_include_the_customer(self):
        sales = sheet_from_rows('Sales', [{
            'receipt_number': 'RCP-1',
            'created_at': '2026-09-25 19:39:00',
            'cashier_name': 'mercy',
            'payment_method': 'm-pesa',
            'total': 1010,
            'customer_name': 'Jane Wanjiku',
        }], [
            'receipt_number', 'created_at', 'cashier_name',
            'payment_method', 'total', 'customer_name',
        ])
        summary = summary_sheet({
            'start': '2026-09-01',
            'end': '2026-09-25',
            'summary': {
                'gross_sales': 5000,
                'cost_of_goods': 2000,
                'gross_profit': 3000,
                'inventory_value': 8000,
            },
        }, can_see_finance=False)
        labels = [row[0] for row in summary['rows']]
        self.assertNotIn('Cost of goods', labels)
        self.assertNotIn('Gross profit', labels)
        sheets = [summary, sales]
        workbook = render_portal_xlsx(
            sheets, shop_name='Edmus', title='Full shop report',
            period='2026-09-01 to 2026-09-25', generated_by='Owner',
        )
        self.assertTrue(workbook.startswith(b'PK'))
        pdf = render_portal_pdf(
            sheets, shop_name='Edmus', title='Full shop report',
            period='2026-09-01 to 2026-09-25',
        )
        self.assertTrue(pdf.startswith(b'%PDF'))
        page = render_portal_html(
            sheets, shop_name='Edmus', title='Sales',
            period='2026-09-01 to 2026-09-25', auto_print=True,
        )
        self.assertIn('Jane Wanjiku', page)
        self.assertIn('RCP-1', page)
        self.assertIn('window.print()', page)
        csv_body = render_portal_csv(sheets)
        self.assertIn('Jane Wanjiku', csv_body)
        self.assertIn('Sales', csv_body)

    def test_html_escapes_customer_text(self):
        sheet = sheet_from_rows('Sales', [{
            'customer_name': '<script>',
            'receipt_number': 'RCP-2',
            'total': 10,
        }], ['customer_name', 'receipt_number', 'total'])
        page = render_portal_html(
            [sheet], shop_name='Shop', title='Sales', period='today',
        )
        self.assertIn('&lt;script&gt;', page)
        self.assertNotIn('<td><script>', page)


if __name__ == '__main__':
    unittest.main()
