from src.alphabet.model import GPTConfig, GPT
from src.write.utils import encode
import torch, time, json, os

class train:
    def __init__(self, n_layer, n_embd, n_head, lr, dropout, block_size, batch_size, device="auto"):
        # hyperparameters
        self.n_layer = n_layer
        self.n_embd = n_embd
        self.n_head = n_head
        self.learning_rate = lr
        self.dropout = dropout
        self.block_size = block_size # what is the maximum context length for predictions?
        self.batch_size = batch_size # how many independent sequences will we process in parallel?
        if device == "auto":
            self.device = 'cuda' if torch.cuda.is_available() else 'cpu'

        else:
            self.device = device

        # print the device
        print("Training on", self.device)

    def preprocess(self, filepath, intent_name, data_division=0.8):
        with open(filepath, "r", encoding="utf-8") as f:
            intents = json.load(f)

        intents = data[intent_name]
        patterns = []
        labels = []

        for intent in intents:
            tag = intent["tag"]
            for pattern in intent["patterns"]:
                patterns.append(pattern)
                labels.append(tag)

        # here are all the unique labels (intents)
        unique_labels = sorted(list(set(labels)))
        self.num_classes = len(unique_labels)

        # create a mapping from labels to integers
        self.intents = {label: i for i, label in enumerate(unique_labels)}
        self.intents_inv = {i: label for label, i in self.intents.items()}

        # create a mapping from patterns to integers
        self.stoi = {pattern: i for i, pattern in enumerate(patterns)}
        self.itos = {i: pattern for pattern, i in self.stoi.items()}

        # Train and test splits
        data = torch.tensor([encode(pattern, stoi=self.stoi) for pattern in patterns], dtype=torch.long)
        n = int(data_division * len(data))  # the first (data_division * 100)% will be train, rest val
        self.train_data = data[:n]
        self.val_data = data[n:]

        # print the number of tokens
        print(len(data)/1e6, "M total tokens")
        print(len(self.train_data)/1e6, "M train tokens,", len(self.val_data)/1e6, "M test tokens")

    # data loading
    def get_batch(self, split):
        # generate a small batch of data of inputs x and targets y
        data = self.train_data if split == 'train' else self.val_data
        ix = torch.randint(len(data) - self.block_size, (self.batch_size,))
        x = torch.stack([data[i:i+self.block_size] for i in ix])
        y = torch.tensor([self.stoi[pattern] for pattern in y[ix]], dtype=torch.long)
        x, y = x.to(self.device), y.to(self.device)
        return x, y

    @torch.no_grad()
    def estimate_loss(self, eval_iters):
        out = {}
        self.model.eval()
        for split in ['train', 'val']:
            losses = torch.zeros(eval_iters)
            for k in range(eval_iters):
                X, Y = self.get_batch(split)
                logits, loss = self.model(X, Y)
                losses[k] = loss.item()
            out[split] = losses.mean()
        self.model.train()
        return out

    def train(self, n_steps, eval_interval, eval_iters, checkpoint_interval=0, checkpoint_path=""):
        """
        @param n_steps: number of Epochs to train the model for
        @param eval_interval: the interval between each loss evaluation
        @param eval_iters: the iterations for each loss evaluation
        @param checkpoint_interval: the interval between each checkpoint save
        @param checkpoint_path: the save path for the checkpoint
        """

        # Set hyperparameters
        GPTConfig.n_embd = self.n_embd
        GPTConfig.n_head = self.n_head
        GPTConfig.n_layer = self.n_layer
        GPTConfig.block_size = self.block_size
        GPTConfig.dropout = self.dropout
        GPTConfig.vocab_size = len(self.stoi)
        GPTConfig.output_size = self.num_classes
        GPTConfig.device = self.device

        # Create an instance of GPT
        self.model = GPT()
        m = self.model.to(self.device)
        # print the number of parameters in the model
        print(sum(p.numel() for p in m.parameters())/1e6, 'M parameters')

        # create a PyTorch optimizer
        optimizer = torch.optim.AdamW(self.model.parameters(), lr=self.learning_rate)

        # start timer
        start_time = time.perf_counter()

        for iter in range(n_steps):
            try:
                if (iter + 1) % eval_interval == 0 or iter == n_steps - 1:
                    losses = self.estimate_loss(eval_iters)
                    print(f"step [{iter + 1}/{n_steps}]: train loss {losses['train']:.4f}, val loss {losses['val']:.4f}")

                # sample a batch of data
                xb, yb = self.get_batch('train')

                # evaluate the loss
                logits, loss = self.model(xb, yb)
                optimizer.zero_grad(set_to_none=True)
                loss.backward()
                optimizer.step()

                if checkpoint_interval != 0 and checkpoint_path != "" and (iter + 1) % checkpoint_interval == 0:
                    # split the filepath into path, filename, and extension
                    path, filename_with_extension = os.path.split(checkpoint_path)
                    filename, extension = os.path.splitext(filename_with_extension)

                    # save the model checkpoint
                    self.save(os.path.join(path, f"{filename}_{(iter + 1)}{extension}"))

            except KeyboardInterrupt:
                break

        print(f"Time taken: {(time.perf_counter() - start_time):.0f} sec")

    def save(self, savepath):
        torch.save(
            {
                "state_dict": self.model.state_dict(),
                "stoi": self.stoi,
                "itos": self.itos,
                "intents": self.intents,
                "intents_inv": self.intents_inv,
                "device": self.device,
                "config": {
                    "n_embd": self.n_embd,
                    "n_head": self.n_head,
                    "n_layer": self.n_layer,
                    "block_size": self.block_size,
                    "num_classes": self.num_classes,
                    "dropout": self.dropout,
                }
            },
            savepath
        )
