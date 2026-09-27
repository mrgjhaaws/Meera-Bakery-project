import mysql.connector
import getpass

password = getpass.getpass("Enter DB password: ")

conn = mysql.connector.connect(
    host="database-1.cpkk888i6wh2.ap-south-1.rds.amazonaws.com",
    user="meera_app",
    password=password,
    database="meera_bakery",
)

with open("../database/schema/08_create_otp_codes.sql", "r") as f:
    sql = f.read()

cursor = conn.cursor()
cursor.execute(sql)
conn.commit()
print("otp_codes table created successfully.")

cursor.close()
conn.close()
