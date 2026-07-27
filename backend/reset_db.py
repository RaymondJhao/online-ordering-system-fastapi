"""開發階段專用：清空並依目前 models.py 重建所有資料表。

MySQL 修改既有 Enum 欄位相對麻煩（要 ALTER TABLE ... MODIFY COLUMN），
開發階段資料可以捨棄時，直接 drop 全部表再 create_all() 最快。

用法（確保 docker-compose 的 MySQL 容器已啟動、且 backend/.env 的
DATABASE_URL 指向該容器）：

    cd backend
    python reset_db.py
"""

from app import create_app
from app.extensions import db

app = create_app()

with app.app_context():
    confirm = input(
        "這會清空 MySQL 中所有資料表並重建，確定要繼續嗎？(輸入 yes 繼續): "
    )
    if confirm.strip().lower() != "yes":
        print("已取消。")
    else:
        db.drop_all()
        db.create_all()
        print("資料表已重建完成。")
