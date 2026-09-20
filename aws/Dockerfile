FROM public.ecr.aws/lambda/python:3.12
RUN microdnf install -y libgomp && microdnf clean all
COPY requirements.txt ${LAMBDA_TASK_ROOT}/requirements.txt
RUN pip install --no-cache-dir -r ${LAMBDA_TASK_ROOT}/requirements.txt
COPY agent ${LAMBDA_TASK_ROOT}/agent
COPY api ${LAMBDA_TASK_ROOT}/api
COPY tools ${LAMBDA_TASK_ROOT}/tools
COPY knowledge_base ${LAMBDA_TASK_ROOT}/knowledge_base
COPY aws ${LAMBDA_TASK_ROOT}/aws
COPY config.py lambda_handler.py ${LAMBDA_TASK_ROOT}/
ENV MPLCONFIGDIR=/tmp/matplotlib NUMBA_CACHE_DIR=/tmp/numba
CMD ["lambda_handler.handler"]
