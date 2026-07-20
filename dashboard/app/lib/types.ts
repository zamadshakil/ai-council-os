export interface Task {
  task_id: string;
  council: string;
  status: 'pending' | 'awaiting_approval' | 'approved' | 'rejected' | 'failed';
  task_description: string;
  final_output: string;
  confidence_score: number;
  iterations: number;
  total_cost_usd: number;
  debate_history: DebateMessage[];
  created_at: string;
  context: Record<string, any>;
}

export interface DebateMessage {
  role: 'generator' | 'critic' | 'synthesizer';
  model: string;
  content: string;
  confidence_score: number;
  timestamp: string;
}

export interface Stats {
  total_tasks: number;
  pending: number;
  approved: number;
  rejected: number;
  total_cost_usd: number;
  avg_confidence: number;
  councils: Record<string, { tasks: number; cost: number; avg_confidence: number }>;
}
