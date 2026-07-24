export interface Task {
  task_id: string;
  council: string;
  status: 'pending' | 'awaiting_approval' | 'approved' | 'rejected' | 'failed' | 'published';
  task_description: string;
  final_output: string;
  confidence_score: number;
  iterations: number;
  total_cost_usd: number;
  debate_history: DebateMessage[];
  created_at: string;
  context: Record<string, any>;
  feedback_notes?: string;
  error?: string;
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

export interface KillSwitchStatus {
  is_active: boolean;
  toggled_by: string;
  toggled_at: string;
  reason: string;
}

export interface WorkflowResult {
  status: string;
  error?: string;
  [key: string]: any;
}
