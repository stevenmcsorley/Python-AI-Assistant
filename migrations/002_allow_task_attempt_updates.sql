-- Allow updates on task_attempts for completion/failure status tracking
DROP TRIGGER IF EXISTS immut_task_attempts ON task_attempts;
