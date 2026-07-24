export const instant = false;

import { TaskDetailContent } from './client-content';

export default async function TaskDetailPage({
  params,
}: {
  params: Promise<{ id: string }>
}) {
  const resolvedParams = await params;
  return <TaskDetailContent id={resolvedParams.id} />;
}
