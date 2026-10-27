from typing import List, Union
import numpy as np


class BaseEmbeddingModel:
    def embed_documents(
        self,
        texts: List[str],
        normalize: bool = False,
        to_list: bool = True,
    ) -> Union[List[List[float]], np.ndarray]:
        raise NotImplementedError

    def embed_query(
        self,
        text: str,
        normalize: bool = False,
        to_list: bool = True,
    ) -> Union[List[float], np.ndarray]:
        # default impl: reuse embed_documents
        result = self.embed_documents([text], normalize=normalize, to_list=to_list)
        return result
