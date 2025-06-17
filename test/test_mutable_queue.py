import unittest
from queue import Empty

from AFL.automation.shared.MutableQueue import MutableQueue


class MutableQueueTestCase(unittest.TestCase):
    def test_put_get(self):
        q = MutableQueue()
        q.put('a', 0)
        q.put('b', 1)
        self.assertEqual(q.qsize(), 2)
        self.assertEqual(q.get(), 'a')
        self.assertEqual(q.get(), 'b')
        self.assertTrue(q.empty())
        with self.assertRaises(Empty):
            q.get(block=False)

    def test_remove(self):
        q = MutableQueue()
        q.put('a', 0)
        q.put('b', 1)
        q.remove(0)
        self.assertEqual(q.qsize(), 1)
        self.assertEqual(q.get(), 'b')
        with self.assertRaises(IndexError):
            q.remove(0)

    def test_move(self):
        q = MutableQueue()
        q.put('a', 0)
        q.put('b', 1)
        q.put('c', 2)
        q.move(0, 2)
        self.assertEqual(list(q.queue), ['b', 'c', 'a'])
        q.move(2, 0)
        self.assertEqual(list(q.queue), ['a', 'b', 'c'])


if __name__ == '__main__':
    unittest.main()
