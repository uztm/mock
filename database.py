import sqlite3
import logging
from datetime import datetime
from typing import Optional, List, Dict, Any
from contextlib import contextmanager

logger = logging.getLogger(__name__)


class Database:
    def get_posts_by_user(self, user_id: int, limit: int = 50) -> List[Dict[str, Any]]:
        """Get all posts by a specific user"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute('''
                               SELECT * FROM posts
                               WHERE user_id = ?
                               ORDER BY created_at DESC
                                   LIMIT ?
                               ''', (user_id, limit))
                return [dict(row) for row in cursor.fetchall()]
        except Exception as e:
            logger.error(f"Error getting user posts: {e}")
            return []

    def get_posts_by_status(self, status: str, limit: int = 50) -> List[Dict[str, Any]]:
        """Get posts by status"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute('''
                               SELECT * FROM posts
                               WHERE status = ?
                               ORDER BY created_at DESC
                                   LIMIT ?
                               ''', (status, limit))
                return [dict(row) for row in cursor.fetchall()]
        except Exception as e:
            logger.error(f"Error getting posts by status: {e}")
            return []

    def add_comment(self, post_id: int, user_id: int, text: str) -> Optional[int]:
        """Add a comment to a post"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute('''
                               INSERT INTO comments (post_id, user_id, text)
                               VALUES (?, ?, ?)
                               ''', (post_id, user_id, text))
                comment_id = cursor.lastrowid
                logger.info(f"Comment {comment_id} added to post {post_id}")
                return comment_id
        except Exception as e:
            logger.error(f"Error adding comment: {e}")
            return None

    def get_comments(self, post_id: int) -> List[Dict[str, Any]]:
        """Get all comments for a post"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute('''
                               SELECT * FROM comments
                               WHERE post_id = ?
                               ORDER BY created_at ASC
                               ''', (post_id,))
                return [dict(row) for row in cursor.fetchall()]
        except Exception as e:
            logger.error(f"Error getting comments: {e}")
            return []

    def get_comment_count(self, post_id: int) -> int:
        """Get comment count for a post"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute('''
                               SELECT COUNT(*) as count FROM comments
                               WHERE post_id = ?
                               ''', (post_id,))
                row = cursor.fetchone()
                return row['count'] if row else 0
        except Exception as e:
            logger.error(f"Error getting comment count: {e}")
            return 0

    def get_user_stats(self, user_id: int) -> Dict[str, int]:
        """Get statistics for a user"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()

                # Get post counts by status
                cursor.execute('''
                               SELECT
                                   COUNT(*) as total_posts,
                                   SUM(CASE WHEN status = 'approved' THEN 1 ELSE 0 END) as approved_posts,
                                   SUM(CASE WHEN status = 'rejected' THEN 1 ELSE 0 END) as rejected_posts,
                                   SUM(CASE WHEN status = 'pending' THEN 1 ELSE 0 END) as pending_posts
                               FROM posts
                               WHERE user_id = ?
                               ''', (user_id,))
                post_stats = cursor.fetchone()

                # Get comment count
                cursor.execute('''
                               SELECT COUNT(*) as total_comments
                               FROM comments
                               WHERE user_id = ?
                               ''', (user_id,))
                comment_stats = cursor.fetchone()

                return {
                    'total_posts': post_stats['total_posts'] or 0,
                    'approved_posts': post_stats['approved_posts'] or 0,
                    'rejected_posts': post_stats['rejected_posts'] or 0,
                    'pending_posts': post_stats['pending_posts'] or 0,
                    'total_comments': comment_stats['total_comments'] or 0
                }
        except Exception as e:
            logger.error(f"Error getting user stats: {e}")
            return {
                'total_posts': 0,
                'approved_posts': 0,
                'rejected_posts': 0,
                'pending_posts': 0,
                'total_comments': 0
            }

    def get_global_stats(self) -> Dict[str, int]:
        """Get global statistics"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()

                # Get user count
                cursor.execute('SELECT COUNT(*) as count FROM users')
                user_count = cursor.fetchone()['count']

                # Get post counts
                cursor.execute('''
                               SELECT
                                   COUNT(*) as total_posts,
                                   SUM(CASE WHEN status = 'approved' THEN 1 ELSE 0 END) as approved_posts,
                                   SUM(CASE WHEN status = 'rejected' THEN 1 ELSE 0 END) as rejected_posts,
                                   SUM(CASE WHEN status = 'pending' THEN 1 ELSE 0 END) as pending_posts
                               FROM posts
                               ''')
                post_stats = cursor.fetchone()

                # Get comment count
                cursor.execute('SELECT COUNT(*) as count FROM comments')
                comment_count = cursor.fetchone()['count']

                return {
                    'total_users': user_count or 0,
                    'total_posts': post_stats['total_posts'] or 0,
                    'approved_posts': post_stats['approved_posts'] or 0,
                    'rejected_posts': post_stats['rejected_posts'] or 0,
                    'pending_posts': post_stats['pending_posts'] or 0,
                    'total_comments': comment_count or 0
                }
        except Exception as e:
            logger.error(f"Error getting global stats: {e}")
            return {
                'total_users': 0,
                'total_posts': 0,
                'approved_posts': 0,
                'rejected_posts': 0,
                'pending_posts': 0,
                'total_comments': 0
            }

    def delete_post(self, post_id: int) -> bool:
        """Delete a post and its comments"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()

                # Delete comments first (foreign key constraint)
                cursor.execute('DELETE FROM comments WHERE post_id = ?', (post_id,))

                # Delete post
                cursor.execute('DELETE FROM posts WHERE post_id = ?', (post_id,))

                logger.info(f"Post {post_id} and its comments deleted")
                return True
        except Exception as e:
            logger.error(f"Error deleting post: {e}")
            return False

    def delete_comment(self, comment_id: int) -> bool:
        """Delete a comment"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute('DELETE FROM comments WHERE comment_id = ?', (comment_id,))
                logger.info(f"Comment {comment_id} deleted")
                return True
        except Exception as e:
            logger.error(f"Error deleting comment: {e}")
            return False

    def search_posts(self, query: str, limit: int = 20) -> List[Dict[str, Any]]:
        """Search posts by text content"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute('''
                               SELECT * FROM posts
                               WHERE status = 'approved' AND text LIKE ?
                               ORDER BY created_at DESC
                                   LIMIT ?
                               ''', (f'%{query}%', limit))
                return [dict(row) for row in cursor.fetchall()]
        except Exception as e:
            logger.error(f"Error searching posts: {e}")
            return []

    def get_recent_approved_posts(self, limit: int = 10) -> List[Dict[str, Any]]:
        """Get recent approved posts"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute('''
                               SELECT p.*,
                                      (SELECT COUNT(*) FROM comments c WHERE c.post_id = p.post_id) as comment_count
                               FROM posts p
                               WHERE status = 'approved'
                               ORDER BY created_at DESC
                                   LIMIT ?
                               ''', (limit,))
                return [dict(row) for row in cursor.fetchall()]
        except Exception as e:
            logger.error(f"Error getting recent posts: {e}")
            return []

    def get_active_users(self, days: int = 7) -> List[Dict[str, Any]]:
        """Get users active in the last N days"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute('''
                               SELECT * FROM users
                               WHERE last_active >= datetime('now', '-' || ? || ' days')
                               ORDER BY last_active DESC
                               ''', (days,))
                return [dict(row) for row in cursor.fetchall()]
        except Exception as e:
            logger.error(f"Error getting active users: {e}")
            return []

    def backup_database(self, backup_path: str) -> bool:
        """Create a backup of the database"""
        try:
            import shutil
            shutil.copy2(self.db_name, backup_path)
            logger.info(f"Database backed up to {backup_path}")
            return True
        except Exception as e:
            logger.error(f"Error backing up database: {e}")
            return False

    def cleanup_old_rejected_posts(self, days: int = 30) -> int:
        """Delete rejected posts older than N days"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute('''
                               DELETE FROM posts
                               WHERE status = 'rejected'
                                 AND created_at < datetime('now', '-' || ? || ' days')
                               ''', (days,))
                deleted_count = cursor.rowcount
                logger.info(f"Deleted {deleted_count} old rejected posts")
                return deleted_count
        except Exception as e:
            logger.error(f"Error cleaning up old posts: {e}")
            return 0;
            """Database manager for the anonymous bot"""

    def __init__(self, db_name: str = "anonymous_bot.db"):
        """Initialize database connection"""
        self.db_name = db_name
        logger.info(f"Database initialized: {db_name}")

    @contextmanager
    def get_connection(self):
        """Context manager for database connections"""
        conn = sqlite3.connect(self.db_name)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        except Exception as e:
            conn.rollback()
            logger.error(f"Database error: {e}")
            raise
        finally:
            conn.close()

    def create_tables(self):
        """Create all necessary tables"""
        with self.get_connection() as conn:
            cursor = conn.cursor()

            # Users table
            cursor.execute('''
                           CREATE TABLE IF NOT EXISTS users (
                                                                user_id INTEGER PRIMARY KEY,
                                                                username TEXT,
                                                                first_name TEXT,
                                                                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                                                                last_active TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                           )
                           ''')

            # Posts table
            cursor.execute('''
                           CREATE TABLE IF NOT EXISTS posts (
                                                                post_id INTEGER PRIMARY KEY AUTOINCREMENT,
                                                                user_id INTEGER NOT NULL,
                                                                text TEXT NOT NULL,
                                                                image_file_id TEXT,
                                                                status TEXT DEFAULT 'pending',
                                                                channel_message_id INTEGER,
                                                                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                                                                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                                                                FOREIGN KEY (user_id) REFERENCES users(user_id)
                               )
                           ''')

            # Comments table
            cursor.execute('''
                           CREATE TABLE IF NOT EXISTS comments (
                                                                   comment_id INTEGER PRIMARY KEY AUTOINCREMENT,
                                                                   post_id INTEGER NOT NULL,
                                                                   user_id INTEGER NOT NULL,
                                                                   text TEXT NOT NULL,
                                                                   created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                                                                   FOREIGN KEY (post_id) REFERENCES posts(post_id),
                               FOREIGN KEY (user_id) REFERENCES users(user_id)
                               )
                           ''')

            # Create indexes for better performance
            cursor.execute('''
                           CREATE INDEX IF NOT EXISTS idx_posts_user_id
                               ON posts(user_id)
                           ''')

            cursor.execute('''
                           CREATE INDEX IF NOT EXISTS idx_posts_status
                               ON posts(status)
                           ''')

            cursor.execute('''
                           CREATE INDEX IF NOT EXISTS idx_comments_post_id
                               ON comments(post_id)
                           ''')

            cursor.execute('''
                           CREATE INDEX IF NOT EXISTS idx_comments_user_id
                               ON comments(user_id)
                           ''')

            logger.info("Database tables created successfully")

    def add_user(self, user_id: int, username: Optional[str], first_name: str) -> bool:
        """Add a new user or update existing user"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute('''
                               INSERT INTO users (user_id, username, first_name, last_active)
                               VALUES (?, ?, ?, CURRENT_TIMESTAMP)
                                   ON CONFLICT(user_id) DO UPDATE SET
                                   username = excluded.username,
                                                               first_name = excluded.first_name,
                                                               last_active = CURRENT_TIMESTAMP
                               ''', (user_id, username, first_name))
                logger.info(f"User {user_id} added/updated")
                return True
        except Exception as e:
            logger.error(f"Error adding user: {e}")
            return False

    def get_user(self, user_id: int) -> Optional[Dict[str, Any]]:
        """Get user information"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute('''
                               SELECT * FROM users WHERE user_id = ?
                               ''', (user_id,))
                row = cursor.fetchone()
                return dict(row) if row else None
        except Exception as e:
            logger.error(f"Error getting user: {e}")
            return None

    def add_post(self, user_id: int, text: str, image_file_id: Optional[str] = None) -> Optional[int]:
        """Add a new post"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute('''
                               INSERT INTO posts (user_id, text, image_file_id)
                               VALUES (?, ?, ?)
                               ''', (user_id, text, image_file_id))
                post_id = cursor.lastrowid
                logger.info(f"Post {post_id} created by user {user_id}")
                return post_id
        except Exception as e:
            logger.error(f"Error adding post: {e}")
            return None

    def get_post(self, post_id: int) -> Optional[Dict[str, Any]]:
        """Get post information"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute('''
                               SELECT * FROM posts WHERE post_id = ?
                               ''', (post_id,))
                row = cursor.fetchone()
                return dict(row) if row else None
        except Exception as e:
            logger.error(f"Error getting post: {e}")
            return None

    def update_post_status(self, post_id: int, status: str,
                           channel_message_id: Optional[int] = None) -> bool:
        """Update post status"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                if channel_message_id:
                    cursor.execute('''
                                   UPDATE posts
                                   SET status = ?, channel_message_id = ?, updated_at = CURRENT_TIMESTAMP
                                   WHERE post_id = ?
                                   ''', (status, channel_message_id, post_id))
                else:
                    cursor.execute('''
                                   UPDATE posts
                                   SET status = ?, updated_at = CURRENT_TIMESTAMP
                                   WHERE post_id = ?
                                   ''', (status, post_id))
                logger.info(f"Post {post_id} status updated to {status}")
                return True
        except Exception as e:
            logger.error(f"Error updating post status: {e}")
            return False