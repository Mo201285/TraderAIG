export function EmptyState({ title, description, hint, lang }: any) {
  return <div>{title}{description ? <p>{description}</p> : null}{hint ? <small>{hint}</small> : null}</div>;
}
export function ErrorState({ message }: { message: string }) {
  return <div>{message}</div>;
}
export function LoadingState() {
  return <div>Loading...</div>;
}
export function StatusChip({ status, lang }: any) {
  return <span>{status}</span>;
}
