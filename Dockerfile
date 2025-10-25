# Python ka ek halka-phulka official version use karo
FROM python:3.10-slim

# Kaam karne ke liye /app naam ka folder banao
WORKDIR /app

# Libraries install karo
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Baaki ka saara project code copy karo
COPY . .

# 'start.sh' ki ab koi zaroorat nahi hai

# Jab container start ho, toh seedhe Python script ko chalao
# Yeh sabse direct aur reliable tareeka hai
CMD ["python3", "main.py"]
