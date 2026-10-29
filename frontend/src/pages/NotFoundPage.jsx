import { Link } from "react-router-dom";

export default function NotFoundPage() {
  return (
    <main className="page-container page-container--narrow not-found">
      <p className="eyebrow">404 · МАРШРУТ НЕ НАЙДЕН</p>
      <h1>Такой страницы нет</h1>
      <p className="page-intro__copy">
        Ссылка могла устареть или содержать неверный идентификатор.
      </p>
      <Link className="button button--primary" to="/">Вернуться к матчам</Link>
    </main>
  );
}
