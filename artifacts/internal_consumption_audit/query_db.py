import sqlite3

c = sqlite3.connect(r'C:\MBT_Build\qa-isolated-consumption\data\mbt_pos.db')
print('consumptions')
for row in c.execute(
    'select reference_no, voided, round(total_cost,2), reason from stock_consumptions order by id'
):
    print(row)
print('stock')
for row in c.execute(
    "select sku, stock from products where sku like 'IC-AUDIT-SOAP%' or sku='IC-AUDIT-ZERO'"
):
    print(row)
print('sales', c.execute('select count(*) from sales').fetchone()[0])
print('moves', c.execute(
    'select movement_type, count(*) from stock_movements group by 1'
).fetchall())
print('audits', c.execute(
    "select action, count(*) from audit_log where action in "
    "('INTERNAL_USE','CREATE_CONSUMPTION','VOID_CONSUMPTION','INTERNAL_USE_VOID') group by 1"
).fetchall())
