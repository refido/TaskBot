# TaskB0t

Automated manual task in specific web applications.

## Installation

create virtual environtment

```bash
python -m venv venv
```

activate virtual environment (Windows)

```bash
venv\Scripts\activate
```

run script

```bash
py main.py
```

install dependencies

```bash
pip freeze > requirements.txt
```

update dependencies

```bash
pip uninstall -r requirements.txt
pip install -r requirements.txt
```

## Usage

- Configure the `.env` file with your application URL and user credentials.
- Run the `main.py` script to automate the login and task execution process.

    ```bash
    py main.py
    ```
