import MatchCard from "./MatchCard.jsx";

export default function MatchList({ matches }) {
  return (
    <div className="match-list">
      {matches.map((match) => (
        <MatchCard key={match.id} match={match} />
      ))}
    </div>
  );
}
