from database import get_db

# Most important algorithms for Zoho + TCS + Wipro (10-12 LPA roles)
essential_algorithms = [
    # PATTERNS - MOST IMPORTANT
    ('Two Pointers', 'Array/String', 'Use two indices to solve problems in O(n)', 'Sorted arrays, pair sum, palindrome check', 'https://youtu.be/On03HWe2tZM', 'https://leetcode.com/tag/two-pointers/'),
    ('Sliding Window', 'Array/String', 'Maintain a window that slides over the array', 'Subarray/substring problems, max sum of size k', 'https://youtu.be/MK-NZ4hN7rs', 'https://leetcode.com/tag/sliding-window/'),
    ('Binary Search', 'Search', 'Divide search space in half each iteration', 'Sorted array search, peak element, square root', 'https://youtu.be/GU7DpgHINWQ', 'https://leetcode.com/tag/binary-search/'),
    
    # ARRAYS & STRINGS - ZOHO FOCUS
    ('Kadane\'s Algorithm', 'Dynamic Programming', 'Find maximum subarray sum in O(n)', 'Maximum subarray, best time to buy stock', 'https://youtu.be/5WZl3MMT0Eg', 'https://leetcode.com/problems/maximum-subarray/'),
    ('Dutch National Flag', 'Sorting', 'Sort array with 3 distinct values', 'Sort 0,1,2; sort colors problem', 'https://youtu.be/4xbWSRZHqac', 'https://leetcode.com/problems/sort-colors/'),
    
    # LINKED LISTS
    ('Fast & Slow Pointers', 'Linked List', 'Two pointers moving at different speeds', 'Cycle detection, middle of linked list', 'https://youtu.be/gBTe7lFR3vc', 'https://leetcode.com/tag/linked-list/'),
    ('Reverse Linked List', 'Linked List', 'Reverse a singly linked list', 'Palindrome linked list, add two numbers', 'https://youtu.be/G0_I-ZF0S38', 'https://leetcode.com/problems/reverse-linked-list/'),
    
    # STACK & QUEUE
    ('Monotonic Stack', 'Stack', 'Maintain increasing or decreasing order', 'Next greater element, daily temperatures', 'https://youtu.be/85LWui3FlVk', 'https://leetcode.com/tag/stack/'),
    ('Queue Implementation', 'Queue', 'Implement queue using stacks or arrays', 'BFS, sliding window maximum', 'https://youtu.be/D6gu-_tmEpQ', 'https://leetcode.com/problems/implement-queue-using-stacks/'),
    
    # RECURSION & BACKTRACKING
    ('Backtracking', 'Recursion', 'Try all possibilities and backtrack', 'Permutations, combinations, N-Queens', 'https://youtu.be/DKCbsiDBN6c', 'https://leetcode.com/tag/backtracking/'),
    
    # SORTING
    ('Quick Sort', 'Sorting', 'Divide and conquer sorting', 'General sorting, quick select', 'https://youtu.be/Hoixgm4-P4M', 'https://www.geeksforgeeks.org/quick-sort/'),
    ('Merge Sort', 'Sorting', 'Divide and conquer stable sort', 'General sorting, inversion count', 'https://youtu.be/4VqmGXwpLqc', 'https://www.geeksforgeeks.org/merge-sort/'),
    
    # HASHING
    ('Hash Map', 'Hashing', 'Key-value pair O(1) lookup', 'Two sum, frequency count, duplicates', 'https://youtu.be/7_nF7vCxVBM', 'https://leetcode.com/tag/hash-table/'),
    
    # TREE
    ('Tree BFS/DFS', 'Tree', 'Level order and depth-first traversals', 'Tree problems, binary tree level order', 'https://youtu.be/pcKY4hjDrxk', 'https://leetcode.com/tag/tree/'),
    
    # DYNAMIC PROGRAMMING
    ('Dynamic Programming Basics', 'Dynamic Programming', 'Break problem into subproblems', 'Climbing stairs, Fibonacci, knapsack', 'https://youtu.be/oBt53YbR9Kk', 'https://leetcode.com/tag/dynamic-programming/'),
    
    # GREEDY
    ('Greedy Algorithms', 'Greedy', 'Make locally optimal choice', 'Activity selection, coin change', 'https://youtu.be/HzeK7g8cD0Y', 'https://leetcode.com/tag/greedy/'),
]

with get_db() as db:
    existing = db.execute("SELECT name FROM algorithms").fetchall()
    existing_names = [e['name'] for e in existing]
    
    added = 0
    
    for algo in essential_algorithms:
        name = algo[0]
        if name not in existing_names:
            db.execute("""
                INSERT INTO algorithms (name, pattern, description, when_to_use, youtube_link, article_link, mastery)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (name, algo[1], algo[2], algo[3], algo[4], algo[5], 'Not Started'))
            print(f"✅ Added: {name}")
            added += 1
        else:
            print(f"⏭️ Already exists: {name}")
    
    db.commit()
    print(f"\n{'='*40}")
    print(f"Added {added} new algorithms!")
    print(f"{'='*40}")
    
    # Show all algorithms
    print("\n📚 ALL ALGORITHMS NOW IN DATABASE:")
    all_algos = db.execute("SELECT name, mastery FROM algorithms ORDER BY name").fetchall()
    for a in all_algos:
        print(f"  • {a['name']}: {a['mastery']}")