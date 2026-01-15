## 仮想環境作成方法

仮想環境にしたいフォルダー下で、以下を実行<br>
`py -3.9 -m venv .venv`<br>
`Set-ExecutionPolicy -Scope CurrentUser RemoteSigned(初回のみ)`<br>

## 仮想環境に入る
`.\.venv\Scripts\Activate.ps1`<br>

## exe化
`python.exe -m pip install --upgrade pip`<br>
`python -m pip install pyinstaller`<br>
`python -m pip install ライブラリー1 ライブラリー2...`<br>
`pyinstaller --onefile --noconsole --name exe化のファイル名 python-code.py`<br>

## ライセンス<br>
作業ディレクトリ下で下記実行<br>
`python C:\GitHub\Auto-Licenser\AutoLicenser.py --clean`<br>
releaseフォルダにexeファイルをコピーしてzip化<br>

## 仮想環境から抜ける方法<br>
`deactivate`<br>
