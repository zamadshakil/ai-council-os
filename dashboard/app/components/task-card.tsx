import Link from 'next/link';
import { Task } from '../lib/types';
import { formatDistanceToNow } from 'date-fns';

const councilColors: Record<string, string> = {
  sales: 'bg-blue-100 text-blue-700 border-blue-200',
  content: 'bg-emerald-100 text-emerald-700 border-emerald-200',
  grant: 'bg-amber-100 text-amber-700 border-amber-200',
  strategy: 'bg-violet-100 text-violet-700 border-violet-200',
};

export function TaskCard({ task }: { task: Task }) {
  const badgeColor = councilColors[task.council.toLowerCase()] || 'bg-zinc-100 text-zinc-700 border-zinc-200';
  const confidenceColor = task.confidence_score >= 80 ? 'bg-green-500' : task.confidence_score >= 60 ? 'bg-amber-500' : 'bg-red-500';

  return (
    <div className="bg-white rounded-lg border border-zinc-200 hover:border-zinc-300 transition-all duration-200 shadow-sm hover:shadow-md p-5 flex flex-col justify-between">
      <div>
        <div className="flex justify-between items-start mb-3">
          <span className={`px-2.5 py-0.5 rounded-full text-xs font-medium border ${badgeColor} capitalize`}>
            {task.council} Council
          </span>
          <span className="text-xs text-zinc-400">
            {formatDistanceToNow(new Date(task.created_at), { addSuffix: true })}
          </span>
        </div>
        <Link href={`/approvals/${task.task_id}`}>
          <h4 className="text-sm font-medium text-zinc-900 line-clamp-2 hover:text-blue-600 transition-colors cursor-pointer mb-4">
            {task.task_description}
          </h4>
        </Link>
        <div className="mb-4">
          <div className="flex justify-between items-center text-xs mb-1">
            <span className="text-zinc-500">Confidence</span>
            <span className="font-medium text-zinc-700">{task.confidence_score.toFixed(0)}%</span>
          </div>
          <div className="w-full h-1.5 bg-zinc-100 rounded-full overflow-hidden">
            <div className={`h-full ${confidenceColor}`} style={{ width: `${task.confidence_score}%` }} />
          </div>
        </div>
      </div>
      
      <div className="flex items-center justify-between border-t border-zinc-100 pt-4 mt-2">
        <div className="flex items-center space-x-3 text-xs">
          <span className="px-2 py-1 bg-zinc-100 rounded text-zinc-600 font-medium">
            ${task.total_cost_usd.toFixed(2)}
          </span>
          <span className="text-zinc-500">
            {task.iterations} iterations
          </span>
        </div>
        {task.status === 'awaiting_approval' && (
          <div className="flex space-x-2">
            <button className="px-3 py-1.5 text-xs font-medium border border-red-200 text-red-600 rounded hover:bg-red-50 transition-colors">
              Reject
            </button>
            <button className="px-3 py-1.5 text-xs font-medium bg-blue-600 text-white rounded hover:bg-blue-700 transition-colors">
              Approve
            </button>
          </div>
        )}
      </div>
    </div>
  );
}
