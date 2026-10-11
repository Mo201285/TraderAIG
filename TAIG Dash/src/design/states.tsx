export function EmptyState({ title, description, hint }: { title: string; description?: string; hint?: string }) {
  return <div>{title}{description ? <p>{description}</p> : null}{hint ? <small>{hint}</small> : null}</div>;
}
export function ErrorState({ message }: { message: string }) {
  return <div>{message}</div>;
}
export function LoadingState() {
  return <div>Loading...</div>;
}
export const StatusChip = ({ status }: { status: string }) => <span>{status}</span>;
