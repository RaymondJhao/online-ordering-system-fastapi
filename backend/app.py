from app import create_app
from app.extensions import db

app = create_app()

if __name__ == "__main__":
    with app.app_context():
        db.create_all()
        print("資料表已建立/確認完成：", list(db.metadata.tables.keys()))

    app.run(debug=True)
