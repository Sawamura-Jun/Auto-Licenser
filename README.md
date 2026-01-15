■仮想環境作成方法
    仮想環境にしたいフォルダー下で、
    py -3.9 -m venv .venv
    Set-ExecutionPolicy -Scope CurrentUser RemoteSigned(初回のみ)

■仮想環境に入る
    .\.venv\Scripts\Activate.ps1

■exe化
    python.exe -m pip install --upgrade pip
    python -m pip install pyinstaller
    python -m pip install ライブラリー1 ライブラリー2...
    pyinstaller --onefile --noconsole --name exe化のファイル名 python-code.py

■ライセンス
    作業ディレクトリ下で下記実行
        python C:\GitHub\Auto-Licenser\AutoLicenser.py --clean
        releaseフォルダにexeファイルをコピーしてzip化

■仮想環境から抜ける方法
    deactivate
