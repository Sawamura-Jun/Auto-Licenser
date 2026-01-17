## 仮想環境作成方法
仮想環境にしたいフォルダー下で、以下を実行
```pwershell
py -3.9 -m venv .venv
Set-ExecutionPolicy -Scope CurrentUser RemoteSigned(初回のみ)
```

## 仮想環境に入る
```pwershell
.\.venv\Scripts\Activate.ps1
````

## exe化
```pwershell
python.exe -m pip install --upgrade pip
python -m pip install pyinstaller
python -m pip install ライブラリー1 ライブラリー2...
pyinstaller --onefile --noconsole --name exe化のファイル名 python-code.py
```

## ライセンス<br>
作業ディレクトリ下で下記実行
```pwershell
python C:\GitHub\Auto-Licenser\AutoLicenser.py --clean
```
releaseフォルダにexeファイルをコピーしてzip化

## 仮想環境から抜ける方法<br>
```pwershell
deactivate
```