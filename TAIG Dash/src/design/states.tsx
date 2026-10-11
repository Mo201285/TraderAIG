export const EmptyState = ({ title, description }: { title: string; description?: string }) => <div>{title}</div>;
export const ErrorState = ({ message }: { message: string }) => <div>{message}</div>;
export const LoadingState = () => <div>Loading...</div>;
export const StatusChip = ({ status }: { status: string }) => <span>{status}</span>;
